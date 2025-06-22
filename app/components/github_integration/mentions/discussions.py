from app.components.github_integration.models import Discussion
from app.setup import gh

DISCUSSION_QUERY = """
query getDiscussion($number: Int!, $org: String!, $repo: String!) {
  repository(owner: $org, name: $repo) {
    discussion(number: $number) {
      body
      title
      number
      user: author {
        login
        html_url: url
        avatar_url: avatarUrl
      }
      created_at: createdAt
      html_url: url
      answer {
        user: author {
          login
          html_url: url
          avatar_url: avatarUrl
        }
      }
    }
  }
}
"""


async def get_discussion(org: str, name: str, number: int) -> Discussion:
    resp = await gh.graphql.arequest(
        DISCUSSION_QUERY, variables={"number": number, "org": org, "repo": name}
    )
    data = resp["repository"]["discussion"]
    data["answered_by"] = (answer := data.pop("answer")) and answer["user"]
    return Discussion(**data)
