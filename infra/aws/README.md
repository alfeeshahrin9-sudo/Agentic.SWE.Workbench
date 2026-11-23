# Optional AWS / Terraform Runner (`infra/aws`)

This module provisions an **optional, isolated AWS EC2 runner** pre-configured with Docker, Python 3.12, and the `agentic-swe-sandbox` container image so you can execute `DockerSandbox` runs and gold-patch evaluations remotely.

## Security Defaults

- **No SSH open by default**: `allowed_ssh_cidr` defaults to `null`; connect securely via AWS Systems Manager (SSM) Session Manager.
- **IMDSv2 enforced**: `http_tokens = "required"` with hop limit `1` (blocks container metadata SSRF).
- **Encrypted storage**: EBS root volume (`gp3`) and S3 artifact bucket use encryption at rest with S3 Public Access Block enabled.
- **Container isolation**: Evaluations run inside `DockerSandbox` with `--network=none`, `--cap-drop=ALL`, `--read-only`, and `AGENTIC_SWE_COMMAND_POLICY_MODE=strict`.

## Usage

```bash
cd infra/aws
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Connect via SSM Session Manager:

```bash
aws ssm start-session --target "$(terraform output -raw runner_instance_id)"
```

Tear down all resources when finished to avoid ongoing AWS charges:

```bash
terraform destroy
```
