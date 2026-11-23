variable "project_name" {
  description = "Prefix used for AWS resources."
  type        = string
  default     = "agentic-swe-runner"
}

variable "aws_region" {
  description = "AWS region to deploy the optional SWE runner."
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type for running DockerSandbox evaluations."
  type        = string
  default     = "t3.medium"
}

variable "vpc_cidr" {
  description = "CIDR block for the isolated runner VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the runner subnet."
  type        = string
  default     = "10.42.1.0/24"
}

variable "allowed_ssh_cidr" {
  description = "Optional CIDR block allowed to SSH (leave null to disable SSH and use SSM Session Manager)."
  type        = string
  default     = null
}

variable "repo_url" {
  description = "Git repository URL cloned onto the runner during bootstrap."
  type        = string
  default     = "https://github.com/alfeeshahrin9-sudo/Agentic.SWE.Workbench.git"
}

variable "sandbox_image" {
  description = "Local Docker image tag built on the runner for DockerSandbox."
  type        = string
  default     = "agentic-swe-sandbox:latest"
}

variable "tags" {
  description = "Additional resource tags."
  type        = map(string)
  default     = {}
}
