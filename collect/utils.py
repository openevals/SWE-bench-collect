import logging
import re
import requests
import time
import json
import os
import subprocess

from bs4 import BeautifulSoup
from ghapi.core import GhApi
from fastcore.net import HTTP404NotFoundError, HTTP403ForbiddenError
from typing import Optional
from dotenv import load_dotenv
from constants import (
    MAP_REPO_TO_REQS_PATHS,
    MAP_REPO_TO_ENV_YML_PATHS,
    SWE_BENCH_URL_RAW,
    NON_TEST_EXTS,
)


logging.basicConfig(
  level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class Repo:
  def __init__(self, owner: str, name: str, token: Optional[str] = None):
    """
    Retrieve target repository and create GhApi tool.
    
    Args:
      owner (str): owner of target repository
      name (str): name of target repository
      token (str): Github token
    """
    self.owner = owner
    self.name = name
    self.token = token
    self.api = GhApi(token=token)
    self.repo = self.call_api(self.api.repos.get, owner=owner, repo=name)
    
  def call_api(self, func: callable, **kwargs) -> dict:
    """
    API call wrapper with rate limit handling (checks every 5 minutes if rate limit is reset)
    
    Args:
      func (callable): API function to call
      **kwargs: keyword arguments to pass to API function
    Return:
      values (dict): response object of `func`
    """
    while True:
      try:
        values = func(**kwargs)
        return values
      except HTTP403ForbiddenError as e:
        while True:
          rl = self.api.rate_limit.get()
          logger.info(f"[{self.owner}/{self.name}] Rate limit exceeded, waiting for 5 minutes, remaining: {rl.resources.core.remaining}")
          if rl.resources.core.remaining > 0:
            break
      except HTTP404NotFoundError as e:
        logger.info(f"[{self.owner}/{self.name}] Resource not found {kwargs}")
        return None
      
  def extract_resolved_issues(self, pull: dict) -> list[str]:
    """
    Extract list of issues referenced by a PR
    
    Args:
      pull (dict): PR dictionary object from Github
    Return:
      resolved_issues (list): list of issue numbers referenced by PR
    """
    # Define 1. issue number regex pattern 2. comment regex pattern 3. keywords
    issues_pat = re.compile(r"(\w+)\s\#(\d+)")
    comments_pat = re.compile(r"(?s)<!--.*?-->")
    keywords = {
      "close",
      "closes",
      "closed",
      "fix",
      "fixes",
      "fixed",
      "resolve",
      "resolves",
      "resolved",
    }
    
    # Construct text to search over for issue numbers from PR body and commit messages
    text = pull.title if pull.title else ""
    text += "\n" + (pull.body if pull.body else "")
    commits = self.get_all_loop(
      self.api.pulls.list_commits,
      pull_number=pull.number, quiet=True
    )
    commit_messages = [commit.commit.message for commit in commits]
    commit_text = "\n".join(commit_messages) if commit_messages else ""
    text += "\n" + commit_text
    
    # Remove comments from text
    text = comments_pat.sub("", text)
    # Look for issue numbers in text via scraping <keyword, number> patterns
    references = dict(issues_pat.findall(text))
    resolved_issues = list()
    if references:
      for word, issue_num in references.items():
        if word.lower() in keywords:
          resolved_issues.append(issue_num)
    return resolved_issues
    
  def get_all_loop(
    self,
    func: callable,
    per_page: int = 100,
    num_pages: Optional[int] = None,
    quiet: bool = False,
    **kwargs,
  ) -> list:
    """
    Return all values from a paginated API endpoint.
    
    Args:
      func (callable): API function to call
      per_page (int): number of values to return per page
      num_pages (int): number of pages to return
      quiet (bool): whether to print progress
      **kwargs: keyword arguments to pass to API function
    """
    page = 1
    args = {
      "owner": self.owner,
      "repo": self.name,
      "per_page": per_page,
      **kwargs
    }
    while True:
      try:
        # Get values from API call
        values = func(**args, page=page)
        yield from values
        if len(values) == 0:
          break
        if not quiet:
          rl = self.api.rate_limit.get()
          logger.info(f"[{self.owner}/{self.name}] Processed page {page} ({per_page} values per page). Remaining calls: {rl.resources.core.remaining}")
        if num_pages is not None and page >= num_pages:
          break
        page += 1
      except Exception as e:
        # Rate limit handling
        logger.error(f"Error processing page {page}: {e}")
        while True:
          rl = self.api.rate_limit.get()
          if rl.resources.core.remaining > 0:
            break
          logger.info(f"[{self.owner}/{self.name}] Waiting for rate limit reset, checking again in 5 minutes")
          time.sleep(60*5)
    if not quiet:
      logger.info(f"[{self.owner}/{self.name}] Processed {(page-1)*per_page + len(values)} values")
    
  def get_all_issues(
    self,
    per_page: int = 100,
    num_pages: Optional[int] = None,
    direction: str = "asc",
    sort: str = "created",
    state: str = "closed",
    quiet: bool = False,
  ) -> list:
    """
    Wrapper for API call to get all issues from repo
    
    Args:
      per_page (int): number of issues to return per page
      num_pages (int): number of pages to return
      direction (str): direction to sort issues
      soft (str): field to sort issues by
      state (str): state of issues to look for
      quiet (bool): whether to print progress
    """
    issues = self.get_all_loop(
      self.api.issues.list_for_repo,
      num_pages=num_pages,
      per_page=per_page,
      direction=direction,
      sort=sort,
      state=state,
      quiet=quiet,
    )
    return issues
  
  def get_all_pulls(
    self, 
    per_page: int = 100,
    num_pages: Optional[int] = None,
    direction: str = "asc",
    sort: str = "created",
    state: str = "closed",
    quiet: str = False,
  ) -> list:
    """
    Wrapper for API call to get all PRs from repo
    
    Args:
      per_page (int): number of PRs to return per page
      num_pages (int): number of pages to return
      direction (str): direction to sort PRs
      sort (str): field to sort PRs by
      state (str): state of PRs to look for
      quiet (bool): whether to print progress
    """
    pulls = self.get_all_loop(
      self.api.pulls.list,
      num_pages=num_pages,
      direction=direction,
      per_page=per_page,
      sort=sort,
      state=state,
      quiet=quiet,
    )
    return pulls


def _extract_hints(pull: dict, repo: Repo, issue_number: int) -> list[str]:
  """
  Extract hints from comments associated with a pull request (before first commit)
  
  Args:
    pull (dict): PR dictionary object from Github
    repo (Repo): Repo object
    issue_number (int): issue number
  Return:
    hints (list): list of hints
  """
  # Get all commits in PR
  commits = repo.get_all_loop(
    repo.api.pulls.list_commits, pull_number=pull["number"], quiet=True
  )
  commits = list(commits)
  if len(commits) == 0:
    # If there are no comments, return no hints
    return []
  # Get time of first commit in PR
  commit_time = commits[0].commit.author.date # str
  commit_time = time.mktime(time.strptime(commit_time, "%Y-%m-%dT%H:%M:%SZ"))
  # Get all comments in PR
  all_comments = repo.get_all_loop(
    repo.api.issues.list_comments, issue_number=issue_number,
    quiet=True
  )
  all_comments = list(all_comments)
  # Iterate through all comments, only keep comments created before first commit
  comments = list()
  for comment in all_comments:
    comment_time = time.mktime(
      time.strptime(comment.updated_at, "%Y-%m-%dT%H:%M:%SZ")
    ) # use updated_at instead of created_at
    if comment_time < commit_time:
      comments.append(comment)
    else:
      break
    # only include information available before the first commit was created
  # Keep text from comments
  comments = [comment.body for comment in comments]
  return comments

def extract_problem_statement_and_hints_django(
  pull: dict, 
  repo: Repo
) -> tuple[str, str]:
  """
  Get problem statement and hints from issues associated with a pull request.
  
  Args:
    pull (dict): PR dictionary object from Github
    repo (Repo): Repo object
  Return:
    text (str): problem statement
    hints (str): hints
  """
  text = ""
  all_hints_text = list()
  for issue_number in pull["resolved_issues"]:
    url = f"https://code.djangoproject.com/ticket/{issue_number}"
    resp = requests.get(url)
    if resp.status_code != 200:
      continue
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # Get problem statement (title + body)
    issue_desc = soup.find("div", {"id": "ticket"})
    title = issue_desc.find("h1", class_="searchable").get_text()
    title = re.sub(r"\s+", " ", title).strip()
    body = issue_desc.find("div", class_="description").get_text()
    body = re.sub(r"\n+", "\n", body)
    body = re.sub(r"    ", "\t", body)
    body = re.sub(r"[ ]{2,}", " ", body).strip()
    text += f"{title}\n{body}\n"
    
    # Get time of first commit in PR
    commits = repo.get_all_loop(
      repo.api.pulls.list_commits, pull_number=pull["number"], quiet=True
    )
    commits = list[commits]
    if len(commits) == 0:
      continue
    commit_time = commits[0].commit.author.date
    commit_time = time.mktime(time.strptime(commit_time, "%Y-%m-%dT%H:%M:%SZ"))
    
    # Get all comments before first commit
    comments_html = soup.find("div", {"id": "changelog"})
    div_blocks = comments_html.find_all("div", class_="change")
    comments = []
    # Loop through each div block
    for div_block in div_blocks:
      # Find the comment text and timestamp
      comment_resp = div_block.find("div", class_="comment")
      timestamp_resp = div_block.find("a", class_="timeline")
      if comment_resp is None or timestamp_resp is None: 
        continue
      
      comment_text = re.sub(r"\s+", " ", comment_resp.text).strip()
      timestamp = timestamp_resp["title"]
      if timestamp.startswith("see timeline at "):
        timestamp = timestamp[len("see timeline at ") :]
      timestamp= time.mktime(time.strptime(timestamp, "%m/%d/%y%H:%M:%S"))
      
      # Append the comment and timestamp as a tuple to the comments list
      if timestamp < commit_time:
        all_hints_text.append((comment_text, timestamp))
    
  return text, all_hints_text
    
def extract_problem_statement_and_hints(pull: dict, repo: Repo) -> tuple[str, str]:
  """
  Extract problem statement from issues associated with a pull request
  
  Args:
    pull (dict): PR dictionary object from Github
    repo (Repo): Repo object
  Return:
    text (str): problem statement
    hints (str): hints
  """
  if repo.name == "django":
    return extract_problem_statement_and_hints_django(pull, repo)
  text = ""
  all_hint_texts = list()
  for issue_number in pull["resolved_issues"]:
    issue = repo.call_api(
      repo.api.issues.get,
      owner=repo.owner,
      repo=repo.name,
      issue_number=issue_number,
    )
    if issue is None:
      continue
    title = issue.title if issue.title else ""
    body = issue.body if issue.body else ""
    text += f"{title}\n{body}\n"
    issue_number = issue.number
    hint_texts = _extract_hints(pull, repo, issue_number)
    hint_text = "\n".join(hint_texts)
    all_hint_texts.append(hint_text)
  return text, "\n".join(all_hint_texts) if all_hint_texts else ""

def extract_patches(pull: dict, repo: Repo) -> tuple[str, str]:
  """
  Get patch and test patch from PR
  
  Args:
    pull (dict): PR dictinoary object from Github
    repo (Repo): Repo object
  Return:
    patch_change_str (str): gold patch
    patch_test_str (str): test patch
  """
  # Convert diff to patch format with "index" lines removed
  patch = requests.get(pull["diff_url"]).text
  if patch.endswith("\n"):
    patch = patch[:-1]
  # Create change patch and test patch
  patch_change, patch_test = [], []
  
  # Flag to determine if current diff block is a test or general change
  # Values: "test", "diff", None
  flag = None
  
  for line in patch.split("\n"):
    # Exclude commit specific metadata
    if line.startswith("index "):
      continue
    # Determine if current diff block is a test or general change
    if line.startswith("diff --git a/"):
      words = set(re.split(r" |_|\/|\.", line.lower()))
      flag = (
        "test"
        if ("test" in words or "tests" in words or "testing" in words)
        else "diff"
      )
      if flag != "test" and not line.strip().endswith(".py"):
        flag = None
    # Append line to separate patch depending on flag status
    if flag == "test":
      patch_test.append(line)
    elif flag == "diff":
      patch_change.append(line)
  
  patch_change_str = "\n".join(patch_change) + "\n" if len(patch_change) > 0 else ""
  patch_test_str = "\n".join(patch_test) + "\n" if len(patch_test) > 0 else ""
  return patch_change_str, patch_test_str


def get_instances(instance_path: str) -> list:
  '''
  Get task instances from the given path
  
  Args: 
    instance_path (str): Path to task instances
  Returns:
    task_instances (list): List of task instances
  '''
  if any([instance_path.endswith(x) for x in ['.jsonl', '.jsonl.all']]):
    task_instances = list()
    with open(instance_path) as f:
      for line in f.readlines():
        task_instances.append(json.loads(line))
    return task_instances
  
  with open(instance_path) as f:
    task_instances = json.load(f)
  return task_instances


def split_instances(input_list: list, n: int) -> list:
  '''
  Split a list into n approximately equal length sublists
  
  Args:
    input_list(list): List to split
    n (int): Number of sublists to split into
  Returns:
    result (list): list of sublists
  '''
  avg_length = len(input_list) // n
  remainder = len(input_list) % n
  result, start = [], 0
  
  for i in range(n):
    length = avg_length + 1 if i < remainder else avg_length
    sublist = input_list[start: start + length]
    result.append(sublist)
    start += length
  
  return result




def get_conda_env_names(conda_source: str, env: dict = None) -> list:
    """
    Get list of conda environment names for given conda path

    Args:
        conda_source (str): Path to conda executable
    Returns:
        env_names (list): List of conda environment names
    """
    # Get list of conda environments
    try:
        conda_envs = subprocess.run(
            f"{conda_source} env list".split(" "), check=True, capture_output=True, text=True, env=env,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        print(f"Error stdout: {e.stdout}")
        print(f"Error stderr: {e.stderr}")
        raise e
    output = conda_envs.stdout
    lines = output.split("\n")
    # Store environment names to list
    env_names = []
    for line in lines:
        if line.startswith("#"):
            continue
        if line.strip() == "":
            continue
        parts = line.split()
        if len(parts) <= 1:
            continue
        env_name = parts[1]
        env_names.append(env_name)
    return env_names


def get_environment_yml(
        instance: dict,
        env_name: str,
        save_path: str = None,
        python_version: str = None,
    ) -> str:
    """
    Get environment.yml for given task instance

    Args:
        instance (dict): SWE Bench Task instance
        env_name (str): Rename retrieved environment.yml to this name
        save_path (str): If provided, save environment.yml to this path
    Returns:
        environment.yml (str): If save_path given, returns path to saved environment.yml.
            Otherwise, returns environment.yml as string
    """
    # Attempt to find environment.yml at each path based on task instance's repo
    path_worked = False

    commit = 'environment_setup_commit' if 'environment_setup_commit' in instance else 'base_commit'
    for req_path in MAP_REPO_TO_ENV_YML_PATHS[instance["repo"]]:
        reqs_url = os.path.join(
            SWE_BENCH_URL_RAW, instance["repo"], instance[commit], req_path
        )
        reqs = requests.get(reqs_url)
        if reqs.status_code == 200:
            path_worked = True
            break
    if not path_worked:
        print(
            f"Could not find environment.yml at paths {MAP_REPO_TO_ENV_YML_PATHS[instance['repo']]}"
        )
        return None

    lines = reqs.text.split("\n")
    cleaned = []
    for line in lines:
        # Rename environment to given name
        if line.startswith("name:"):
            cleaned.append(f"name: {env_name}")
            continue
        if line.startswith("dependencies:"):
            cleaned.append(line)
            if python_version is not None:
                cleaned.append(f"  - python={python_version}")
            continue
        cleaned.append(line)

    # Return environment.yml as string if no save path given
    if save_path is None:
        return "\n".join(cleaned)

    # Save environment.yml to given path and return path
    path_to_reqs = os.path.join(save_path, "environment.yml")
    with open(path_to_reqs, "w") as f:
        f.write("\n".join(cleaned))
    return path_to_reqs


def get_requirements(instance: dict, save_path: str = None):
    """
    Get requirements.txt for given task instance

    Args:
        instance (dict): task instance
        save_path (str): If provided, save requirements.txt to this path
    Returns:
        requirements.txt (str): If save_path given, returns path to saved requirements.txt.
            Otherwise, returns requirements.txt as string
    """
    # Attempt to find requirements.txt at each path based on task instance's repo
    path_worked = False
    commit = 'environment_setup_commit' if 'environment_setup_commit' in instance else 'base_commit'

    for req_path in MAP_REPO_TO_REQS_PATHS[instance["repo"]]:
        reqs_url = os.path.join(
            SWE_BENCH_URL_RAW, instance["repo"], instance[commit], req_path
        )
        reqs = requests.get(reqs_url)
        if reqs.status_code == 200:
            path_worked = True
            break
    if not path_worked:
        print(
            f"Could not find requirements.txt at paths {MAP_REPO_TO_REQS_PATHS[instance['repo']]}"
        )
        return None

    lines = reqs.text
    original_req = []
    additional_reqs = []
    req_dir = "/".join(req_path.split("/")[:-1])
    exclude_line = lambda line: any(
        [line.strip().startswith(x) for x in ["-e .", "#", ".[test"]]
    )

    for line in lines.split("\n"):
        if line.strip().startswith("-r"):
            # Handle recursive requirements
            file_name = line[len("-r") :].strip()
            reqs_url = os.path.join(
                SWE_BENCH_URL_RAW,
                instance["repo"],
                instance[commit],
                req_dir,
                file_name,
            )
            reqs = requests.get(reqs_url)
            if reqs.status_code == 200:
                for line_extra in reqs.text.split("\n"):
                    if not exclude_line(line_extra):
                        additional_reqs.append(line_extra)
        else:
            if not exclude_line(line):
                original_req.append(line)

    # Combine all requirements into single text body
    additional_reqs.append("\n".join(original_req))
    all_reqs = "\n".join(additional_reqs)

    if save_path is None:
        return all_reqs

    path_to_reqs = os.path.join(save_path, "requirements.txt")
    with open(path_to_reqs, "w") as f:
        f.write(all_reqs)
    return path_to_reqs


def get_test_directives(instance: dict) -> list:
    """
    Get test directives from the test_patch of a task instance

    Args:
        instance (dict): task instance
    Returns:
        directives (list): List of test directives
    """
    # For seq2seq code repos, testing command is fixed
    if any([
        x == instance["repo"] for x in
        ["humaneval", "humanevalfix-python"]
    ]):
        return ["test.py"]

    # Get test directives from test patch and remove non-test files
    diff_pat = r"diff --git a/.* b/(.*)"
    test_patch = instance["test_patch"]
    directives = re.findall(diff_pat, test_patch)
    directives = [
        d for d in directives if not any(d.endswith(ext) for ext in NON_TEST_EXTS)
    ]

    # For Django tests, remove extension + "tests/" prefix and convert slashes to dots (module referencing)
    if instance["repo"] == "django/django":
        directives_transformed = []
        for d in directives:
            d = d[: -len(".py")] if d.endswith(".py") else d
            d = d[len("tests/") :] if d.startswith("tests/") else d
            d = d.replace("/", ".")
            directives_transformed.append(d)
        directives = directives_transformed

    return directives


def clone_repo(repo_name: str, path: str, token: Optional[str] = None) -> bool:
    """
    Wrapper for cloning repo from swe-bench organization

    Args:
        repo_name (str): Name of repo to clone
        path (str): Path to clone repo to
        token (str): GitHub token to use for cloning
    Returns:
        success (bool): True if repo cloned successfully, False otherwise
    """
    if token is None:
      load_dotenv()
      token = os.getenv("GITHUB_TOKEN")
      if not token: raise Exception("Missing Github token. Please add an appropriate Github token to your .env file.")
      
    try:
        repo_url = (
            f"https://{token}@github.com/swe-bench/"
            + repo_name.replace("/", "__")
            + ".git"
        )
        Repo.clone_from(repo_url, path)
        return True
    except Exception as e:
        print(e)
        return False

