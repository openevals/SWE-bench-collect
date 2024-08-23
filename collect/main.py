from get_valid_tasks import construct_data_files
from dotenv import load_dotenv
import os

def main():
    load_dotenv()  
    token = os.getenv("GITHUB_TOKEN")
  
    print("Welcome! Thanks for helping contribute private programming evals. This is an easy command line interface to create and submit new tasks adhering to the SWE-bench format for your repository.")
    print(f"""
We currently support submissions that adhere to the following requirements:
- Private
- Github repository
- Written in Python
- Uses Pytest as testing framework

We welcome PRs to add support for other configurations ❤️ https://github.com/openevals/swe-bench! (forked from https://github.com/princeton-nlp/SWE-bench)
    """)
    
    print("To start, please provide the name of your Github repositories in the format '<username>/<repo>'.\nExample: `scikit-learn/scikit-learn justanexperiment/bmo-cafe`")
    
    while True:
        try:
          
          repos_str = input("> ")
          repos = repos_str.split()
          
          if token is None or token == '':
            print("Next, please provide your Github authentication token. This is stored locally.")
            token = input("> ")
            if not os.path.exists('.env'):
                with open('.env', 'w') as env_file:
                    env_file.write(f"GITHUB_TOKEN={token}\n")
            else:
                with open('.env', 'r+') as env_file:
                    lines = env_file.readlines()
                    env_file.seek(0)
                    for line in lines:
                        if line.startswith("GITHUB_TOKEN="):
                            env_file.write(f"GITHUB_TOKEN={token}\n")
                        else:
                            env_file.write(line)
                    env_file.truncate()
            print("Thanks! Your token is saved in a .env file.")
          
          print("Pulling repo...")
          
          for repo in repos:
              os.system(f"./collect/make_repo.sh {repo}")
          
          print("Pulling task instances from repo...")
          
          construct_data_files(repos, token)

        except KeyboardInterrupt:
            break
        
        except Exception as e:
            print(f"An error occurred: {e}")
            break

        
if __name__ == "__main__":
    main()
