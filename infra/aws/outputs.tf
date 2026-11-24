output "runner_instance_id" {
  description = "EC2 instance ID of the SWE workbench runner (connect via AWS SSM)."
  value       = aws_instance.runner.id
}

output "artifacts_bucket_name" {
  description = "Encrypted S3 bucket for evaluation reports and run artifacts."
  value       = aws_s3_bucket.artifacts.bucket
}

output "runner_iam_role_arn" {
  description = "Least-privilege IAM role ARN attached to the runner."
  value       = aws_iam_role.runner.arn
}

output "security_group_id" {
  description = "Security group ID attached to the runner."
  value       = aws_security_group.runner.id
}
