# Evals

This is an easy command line interface to create new SWE-bench task instances from your repository. A LLM will auto-verify your submission based on the SWE-bench annotations.

# To submit

Please ensure you've installed [Poetry](https://python-poetry.org/docs/#installation). Please also have your Github authentication token and Anthropic API key on hand. 

Then, run the following commands from the root folder:

```
poetry install
poetry run python collect/main.py
```

You'll be guided through the entire flow. ^^ 