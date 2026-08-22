## Description: <br>
Runs an Atlassian MCP server in Docker so an agent can query Jira, search Confluence, and interact with Atlassian services. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[atakanermis](https://clawhub.ai/user/atakanermis) <br>

### License/Terms of Use: <br>


## Use Case: <br>
Developers and teams use this skill to connect an agent to Jira and Confluence through the Model Context Protocol for issue queries, Confluence search, and Atlassian workflow actions. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Jira credentials are passed to an unpinned third-party Docker container. <br>
Mitigation: Use a dedicated least-privilege Atlassian account or token and pin the Docker image to a reviewed digest or version before deployment. <br>
Risk: Agent-driven Jira actions could create, update, delete, or manage project data without adequate guardrails. <br>
Mitigation: Require explicit approval before Jira write, delete, or project-management actions and scope Atlassian permissions to the minimum needed. <br>
Risk: API tokens may be exposed through shell history, shared logs, or broad environment access. <br>
Mitigation: Provide tokens through protected secret handling and avoid echoing or storing credentials in shared logs. <br>


## Reference(s): <br>
- [ClawHub skill page](https://clawhub.ai/atakanermis/skills/atlassian-mcp) <br>
- [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens) <br>


## Skill Output: <br>
**Output Type(s):** [Text, Markdown, Shell commands, Configuration, Guidance] <br>
**Output Format:** [Markdown with inline bash code blocks and environment variable configuration] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Requires Docker and Jira credentials; execution starts a third-party MCP container.] <br>

## Skill Version(s): <br>
1.0.0 (source: ClawHub release evidence) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
