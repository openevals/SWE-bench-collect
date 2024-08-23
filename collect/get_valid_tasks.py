#!/usr/bin/env python3

"""
This is a script that collects pull requests from a remote Github repository and
converts them into filtered tasks.
"""
import argparse
import os
import traceback
import logging

from dotenv import load_dotenv
from multiprocessing import Pool
from create_task_instances import main as create_task_instances
from retrieve_pull_requests import main as retrieve_pulls

from llm_verified.verify import verify_task_instances

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("get_valid_tasks")
  
def construct_data_files(repos: list, token=None):
  """
  Combine multiple .all PR files into one fine-tuning dataset.
  
  Args:
    repos (list): List of repository names from which to retrieve instruction data
  """
  if token is None:
    load_dotenv()
    token = os.getenv("GITHUB_TOKEN")
    if not token: raise Exception("Missing Github token. Please add an appropriate Github token to your .env file.")
    
  path_prs, path_tasks, path_logs, path_temp_dir = os.path.abspath('data/prs'), os.path.abspath('data/tasks'), os.path.abspath('data/logs'), os.path.abspath('data/temp_dir')
  # Create folders if they don't exist
  for path in [path_prs, path_tasks, path_logs, path_temp_dir]:
    if not os.path.exists(path):
      os.makedirs(path)
      logger.info(f'Created folder: {path}')
  
  logger.info(f'Received following repos to create task instances for: {repos}\nPRs will be saved at {path_prs}.\nTask instances will be saved at {path_tasks}')
  
  for repo in repos:
    logger.info(f'PROCESSING REPO: {repo}')
    repo = repo.strip(",").strip()
    repo_name = repo.split("/")[1]
    try:
      
      # ----- 1. Get PRs from repo -----
      logger.info(f'STEP 1: Getting Github PRs')
      path_pr = os.path.join(path_prs, f"{repo_name}-prs.jsonl")
      if not os.path.exists(path_pr):
        logger.info(f"Pull request data for {repo} not found locally. Pulling......Depending on how many PRs there are this will take some time! Let us cook ☕️")
        retrieve_pulls(repo, path_pr, token)
        logger.info(f"Successfully saved PR data for {repo} to {path_pr}")
      else:
        logger.info(f"Pull request data for {repo} already exists at {path_pr}, skipping...")

      # ----- 2. Create task instances filtered for steps 1 and 2 specified in SWE-bench -----
      logger.info(f'STEP 2: Creating task instances')
      path_task = os.path.join(path_tasks, f"{repo_name}-task-instances.jsonl")
      if not os.path.exists(path_task):
        logger.info(f"Task instance data for {repo} not found locally. Creating...")
        create_task_instances(path_pr, path_task, token)
        logger.info(f"Successfully saved task instance data for {repo} to {path_task}")
      else:
        logger.info(f"Task instance data for {repo} already exists at {path_task}. Skipping...")
      
      # It only does 1 repo at a time for now
      
    
      # ----- 3. Check versions for task instances -----
      logger.info('STEP 3: Checking versions for task instances')
      args = argparse.Namespace(
        instances_path=path_task,
        log_dir=path_logs,
        conda_link=None,
        log_suffix=None,
        path_conda=None,
        testbed=None,
        temp_dir=path_temp_dir,
        timeout=None,
        verbose=True,
        num_workers=1,
      )
      # validate_task_runs(args)
      logger.info('Skipping for now...')

      # ----- 4. Check installation configurations for task instances -----
      logger.info('STEP 4: Checking installation configurations for task instances')
      logger.info('Skipping for now...')
      
      # ----- 5. Check task instances are installed properly, filtered for step 3 specified in SWE-bench  -----
      logger.info('STEP 5: Checking correct installation for task instances, to filter for part 3')
      logger.info('Skipping for now...')
      
      # ----- 6. Check the tasks are properly formatted
      logger.info('FINAL STEP: Verifying with LLM grader that your instances are good. This implements the checks in SWE-bench Verified')
      verify_task_instances(repo_name=repo_name)


      print(f"Awesome! We've retrieved the info. 🎉 It is located in the `data` folder. Please submit prs/{repo}-prs.jsonl, tasks/{repo}-task-instances.jsonl, tasks/{repo}-task-instances.jsonl.all, and tasks-verified/{repo}-results.jsonl to us and we'll review :) Zip file of the `data` folder works too ")

      
    except Exception as e:
      logger.error(f"Something went wrong while creating tasks for the repo {repo}: {e}")
      logger.error("Traceback:")
      traceback.print_exc()
      
      
  
if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--repos", nargs="+", help="List of repositories"
  )
  args = parser.parse_args()
  
  if args.repos is None:
    raise ValueError("No repositories provided. Please specify repositories with the --repos argument.")
  
  # construct_data_files(args.repos, TOKEN)
  construct_data_files(args.repos)