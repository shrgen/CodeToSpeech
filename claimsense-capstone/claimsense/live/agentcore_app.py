"""Amazon Bedrock AgentCore Runtime entrypoint.

Deploy with the AgentCore starter toolkit (see deploy/AGENTCORE.md):
    agentcore configure -e claimsense/live/agentcore_app.py
    agentcore launch --env CLAIMSENSE_BRAIN=bedrock
Invoke payload: {"user_id": "alice", "claim_id": "CLM-2024-1800", "note": ""}
"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from claimsense.service import handle

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    return handle(payload or {})


if __name__ == "__main__":
    app.run()
