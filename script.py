import os
import re
import pandas as pd
from gql import gql, Client
from dotenv import load_dotenv
from urllib.parse import urlparse
from gql.transport.requests import RequestsHTTPTransport

def main():
  load_dotenv()
  token = os.getenv('GITHUB_TOKEN')

  csv_file = "github_auto_repos.csv"

  df = pd.read_csv(csv_file)
  repo_list = df["issue_tracker"].tolist()

  # Setup HTTP transport
  transport = RequestsHTTPTransport(
    url="https://api.github.com/graphql",
    headers={
      "Authorization": f"Bearer {token}"
    },
    verify=True,
    retries=3,
  )

  # Initialize the client
  client = Client(transport=transport, fetch_schema_from_transport=True)
  rate_limit = dict()

  # Execute the query
  for url in repo_list:
    print(f"Analyzing URL: {url}")
    parsed_url = urlparse(url)

    # Check if the URL is from GitHub
    if parsed_url.netloc != 'github.com':
      print(f"Skipping non-GitHub URL: {url}")
      continue

    # Split the path to extract the owner and repo name
    path_parts = parsed_url.path.strip('/').split('/')
    if len(path_parts) >= 2:
      rate_limit = fetch_pull_requests(client, path_parts[0], path_parts[1])

      print(f"API Rate Limit:")
      print(f"  Limit: {rate_limit['limit']}")
      print(f"  Cost: {rate_limit['cost']}")
      print(f"  Remaining: {rate_limit['remaining']}")
      print(f"  Resets at: {rate_limit['resetAt']}")
    else:
      print(f"Invalid GitHub URL format: {url}")

    if rate_limit['remaining'] <= 100:
      print(f"Approaching rate limit quota...Stopped at {url}.")
      break

  print("Script execution is complete!")


def fetch_pull_requests(client, owner, repo, per_page=10):
  output_csv_file = "repo_test_results.csv"
  pr_has_next_page = True
  end_cursor = None
  has_test_file = False
  rate_limit = {}

  # Loop through the pages of pull requests
  while pr_has_next_page:
    # Define the GraphQL query for pull requests
    query = gql(f"""
    {{
      repository(owner: "{owner}", name: "{repo}") {{
        pullRequests(first: {per_page}, orderBy: {{field: CREATED_AT, direction: DESC}}, after: {"null" if end_cursor is None else '"' + end_cursor + '"'}) {{
          edges {{
            node {{
              number
              title
              body
              createdAt
              state
              url
              author {{
                login
              }}
              merged
              mergedAt
            }}
          }}
          pageInfo {{
            endCursor
            hasNextPage
          }}
        }}
      }}
      rateLimit {{
        limit
        cost
        remaining
        resetAt
      }}
    }}
    """)

    response = client.execute(query)

    # Extract pull requests data
    pull_requests = response['repository']['pullRequests']['edges']
    rate_limit = response['rateLimit']

    # Handle pagination for pull requests
    page_info = response['repository']['pullRequests']['pageInfo']
    pr_has_next_page = page_info['hasNextPage']
    end_cursor = page_info['endCursor']

    # Iterate through pull requests and fetch modified files
    for pr in pull_requests:
      pr_node = pr['node']
      print(f"Pull Request #{pr_node['number']}: {pr_node['title']}")
      print(f"Created At: {pr_node['createdAt']}")
      print(f"URL: {pr_node['url']}")
      print(f"State: {pr_node['state']}")
      print(f"Merged: {pr_node['merged']}")

      # Handle pagination for files in each pull request
      file_has_next_page = True
      file_end_cursor = None

      while file_has_next_page:
        query_files = gql(f"""
          {{
            repository(owner: "{owner}", name: "{repo}") {{
              pullRequest(number: {pr_node['number']}) {{
                files(first: {per_page}, after: {"null" if file_end_cursor is None else '"' + file_end_cursor + '"'}) {{
                  edges {{
                    node {{
                      path
                      additions
                      deletions
                      changeType
                    }}
                  }}
                  pageInfo {{
                    endCursor
                    hasNextPage
                  }}
                }}
              }}
            }}
          }}
        """)

        # Execute the files query
        response_files = client.execute(query_files)
        files = response_files['repository']['pullRequest']['files']['edges']

        # Process the modified files
        for file in files:
          file_path = file['node']['path']
          print(f"File: {file_path}")

          # function call to check if file is a testfile i.e contains unit tests or integration tests for android projects (using kotlin or java)
          if is_test_file(file_path):
            has_test_file = True
            repo_data = {
              'owner': [owner], 
              'repository': [repo], 
              'pr_number': [pr_node['number']],
              'pr_title': [pr_node['title']],
              'pr_url': [pr_node['url']],
              'test_file': [file_path]
            }
            # Convert to a DataFrame
            repo_data_df = pd.DataFrame(repo_data)
            repo_data_df.to_csv(output_csv_file, mode='a', header=not os.path.exists(output_csv_file), index=False)
            break

        if has_test_file:
          break

        # Update pagination info for files
        file_page_info = response_files['repository']['pullRequest']['files']['pageInfo']
        file_has_next_page = file_page_info['hasNextPage']
        file_end_cursor = file_page_info['endCursor']

      if has_test_file:
        break # Move to the next repository

    if has_test_file:
      break # Move to the next repository
  
  return rate_limit


def is_test_file(file_path):
    """
    Check if the given file is likely to be a test file for Android projects.
    """
    # Patterns to match test file names and paths
    test_file_patterns = [
        r'.*Test\.kt$',
        r'.*Test\.java$',
        r'.*Tests\.kt$',
        r'.*Tests\.java$',
        r'.*/test/.*\.kt$',
        r'.*/test/.*\.java$',
        r'.*/androidTest/.*\.kt$',
        r'.*/androidTest/.*\.java$'
    ]

    # Check if the file path matches any of the test file patterns
    return any(re.match(pattern, file_path) for pattern in test_file_patterns)


if __name__ == '__main__':
  main()