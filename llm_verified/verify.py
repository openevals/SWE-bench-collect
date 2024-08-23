from typing import Annotated, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode
from pprint import pprint
from langchain_core.pydantic_v1 import BaseModel, Field
import json
import os 
import logging

from llm_verified.prompts import system_message, q_1_1, q_1_2, q_2_1, q_2_2, q_3_1, q_3_2, q_3_3_1, q_3_3_2, q_3_4, q_3_5


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("verify")

# --- VARIABLES ---

class VerificationResult(TypedDict):
    underspecified_notes: str
    underspecified: int
    false_negative_notes: str
    false_negative: int
    other_notes: str
    other_major_issues: int
    filter_out: bool
    
# --- START AI TOOLING LOGIC ---

class FalseNegative(BaseModel):
    rank: int = Field(description=f"""Return a rank from 0 to 3 whether response is well-specified. Grades:
- 0: The issue is well-specified and it is clear what is required for a successful solution. 
- 1: There are some blanks to fill in about the issue, but there is a sensible interpretation of what is required for a successful solution. 
- 2: The issue is vague and there is room for ambiguity. It is unclear what a successful solution would look like.
- 3: It is almost impossible to understand what you are being asked to do without further information.""")

class Underspecified(BaseModel):
    rank: int = Field(description=f"""Return a rank from 0 to 3 whether the response is well-scoped. Grades:
- 0: The tests perfectly cover all possible solutions. 
- 1: The tests cover the majority of correct solutions, however some unusual solutions may be missed. 
- 2: The tests work but some perfectly reasonable solutions may be missed by the tests. 
- 3: The tests are too narrow/broad or they look for something different than what the issue is about.""")

class MajorIssuesExplanation(BaseModel):
    rank: int = Field(description=f"""Response with 0 if there are no major issues. Response with 1 if there are major issues.
- 0: No 
- 1: Yes""")


def get_verification_result(repo: str, patch: str, test_patch: str, problem_statement: str) -> tuple[VerificationResult, list[BaseMessage]]:
    
    vr = VerificationResult(
        underspecified_notes="",
        underspecified=0,
        false_negative_notes="",
        false_negative=0,
        other_notes="",
        other_major_issues=0,
        filter_out=False
    )
    
    messages =  [
        SystemMessage(content= system_message(repo, '')),
        HumanMessage(content=q_1_1(problem_statement))
    ]

    model_1_1 = ChatAnthropic(model="claude-3-5-sonnet-20240620", temperature=0)

    a_1_1 = model_1_1.invoke(messages)
    vr['underspecified_notes'] = a_1_1.content
    
    messages.append(AIMessage(content=vr['underspecified_notes']))
    messages.append(HumanMessage(content=q_1_2()))
    
    model_1_2 = ChatAnthropic(model="claude-3-5-sonnet-20240620", temperature=0).with_structured_output(FalseNegative, method="json_mode")
    
    a_1_2 = model_1_2.invoke(messages)
    vr['underspecified'] = a_1_2.rank
    
    messages.append(AIMessage(content=str(vr['underspecified'])))
    messages.append(HumanMessage(content=q_2_1(
        gold_patch=patch,
        test_patch=test_patch
    )))
    
    model_2_1 = ChatAnthropic(model="claude-3-5-sonnet-20240620", temperature=0)
    
    a_2_1 = model_2_1.invoke(messages)
    vr['false_negative_notes'] = a_2_1.content
    
    messages.append(AIMessage(content=vr['false_negative_notes']))
    messages.append(HumanMessage(content=q_2_2()))
    
    model_2_2 = ChatAnthropic(model="claude-3-5-sonnet-20240620", temperature=0).with_structured_output(FalseNegative, method="json_mode")
    
    a_2_2 = model_2_2.invoke(messages)
    vr['false_negative'] = a_2_2.rank
    
    messages.append(AIMessage(content=str(vr['false_negative'])))
    messages.append(HumanMessage(content=q_3_3_1()))
    
    model_3_3_1 = ChatAnthropic(model="claude-3-5-sonnet-20240620", temperature=0)
    
    a_3_3_1 = model_3_3_1.invoke(messages)
    vr['other_notes'] = a_3_3_1.content
    
    messages.append(AIMessage(content=vr['other_notes']))
    messages.append(HumanMessage(content=q_3_3_2()))
    
    model_3_3_2 = ChatAnthropic(model="claude-3-5-sonnet-20240620", temperature=0).with_structured_output(MajorIssuesExplanation, method="json_mode")
    
    a_3_3_2 = model_3_3_2.invoke(messages)
    vr['other_major_issues'] = a_3_3_2.rank
    
    messages.append(AIMessage(content=vr['other_major_issues']))
    
    if vr["false_negative"] > 1 or vr["underspecified"] > 1 or vr["other_major_issues"] == 1:
        vr["filter_out"] = True

    return vr, messages

def verify_task_instances(repo_name: str):
    
    path_task_instances = os.path.join("data", "tasks", f"{repo_name}-task-instances.jsonl")
    path_output_verification = os.path.join("data", "tasks-verified", f"{repo_name}-results.jsonl")

    if not os.path.exists(path_task_instances):
        logger.error(f"Task instances file for {repo_name} not found at {path_task_instances}. Skipping verification step.")
    else:
        logger.info(f"Verifying task instances for {repo_name} using LLM grader.")
        with open(path_task_instances, 'r') as file:
            task_instances = [json.loads(line) for line in file]

        for instance in task_instances:
            instance_id = instance["instance_id"]
            repo = instance["repo"]
            patch = instance["patch"]
            test_patch = instance["test_patch"]
            problem_statement = instance["problem_statement"]

            vr, messages = get_verification_result(repo, patch, test_patch, problem_statement)
            result = {
                "task_instance": instance,
                "verification_result": vr,
                "messages": [str(message) for message in messages]
            }

            with open(path_output_verification, 'w') as outfile:
                logger.info(f"Instance ID: {instance_id}, Underspecified: {vr['underspecified']}, False Negative: {vr['false_negative']}, Other Major Issues: {vr['other_major_issues']}, Filtered Out: {vr['filter_out']}")
                json.dump(result, outfile)
                outfile.write("\n")

        logger.info(f"Verification results saved to {path_output_verification}")
      

if __name__ == "__main__":
    
    task_instance = None
    # Open the .jsonl file
    with open('example/task_instance_good.json', 'r') as file:
        # Read the entire file
        file_content = file.read()
        # Parse the JSON object
        task_instance = json.loads(file_content)
    # Destructure the task_instance dictionary
    repo = task_instance["repo"]
    patch = task_instance["patch"]
    test_patch = task_instance["test_patch"]
    problem_statement = task_instance["problem_statement"]
    
    if task_instance:
        vr, messages = get_verification_result(repo, patch, test_patch, problem_statement)

        output_data = {
            "messages": [str(message) for message in messages],
            "verificationresult": vr
        }

        with open("example/output_task_instance_good.jsonl", "w") as outfile:
            json.dump(output_data, outfile)
            outfile.write("\n")
