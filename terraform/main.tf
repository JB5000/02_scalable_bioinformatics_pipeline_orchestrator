terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "orchestrator-terraform-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "orchestrator-terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Environment = var.environment
      Project     = "bioinformatics-orchestrator"
      ManagedBy   = "terraform"
    }
  }
}

# VPC
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "orchestrator-vpc"
  }
}

# Subnets
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 1}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "orchestrator-private-subnet-${count.index + 1}"
  }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index + 101}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "orchestrator-public-subnet-${count.index + 1}"
  }
}

# RDS Database
resource "aws_rds_cluster" "orchestrator" {
  cluster_identifier      = "orchestrator-postgres"
  engine                  = "aurora-postgresql"
  engine_version          = "15.2"
  master_username         = var.db_username
  master_password         = var.db_password
  database_name           = "orchestrator"
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  backup_retention_period = 30
  skip_final_snapshot     = var.environment != "prod"

  tags = {
    Name = "orchestrator-postgres"
  }
}

resource "aws_rds_cluster_instance" "orchestrator" {
  count              = 2
  cluster_identifier = aws_rds_cluster.orchestrator.id
  instance_class     = "db.t3.medium"
  engine              = aws_rds_cluster.orchestrator.engine
  engine_version      = aws_rds_cluster.orchestrator.engine_version

  tags = {
    Name = "orchestrator-postgres-instance-${count.index + 1}"
  }
}

resource "aws_db_subnet_group" "main" {
  name       = "orchestrator-db-subnet"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "orchestrator-db-subnet-group"
  }
}

# ElastiCache Redis
resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "orchestrator-redis"
  engine               = "redis"
  engine_version       = "7.0"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  security_group_ids   = [aws_security_group.redis.id]
  subnet_group_name    = aws_elasticache_subnet_group.main.name

  tags = {
    Name = "orchestrator-redis"
  }
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "orchestrator-redis-subnet"
  subnet_ids = aws_subnet.private[*].id
}

# Batch Job Queue
resource "aws_batch_compute_environment" "main" {
  compute_environment_name = "orchestrator-compute-env"
  type                     = "MANAGED"
  state                    = "ENABLED"
  service_role             = aws_iam_role.batch_service.arn

  compute_resources {
    type                = "EC2"
    alloc_strategy      = "SPOT_CAPACITY_OPTIMIZED"
    min_vcpus           = 0
    max_vcpus           = var.batch_max_vcpus
    desired_vcpus       = 0
    instance_type       = ["optimal"]
    subnets             = aws_subnet.private[*].id
    security_group_ids  = [aws_security_group.batch.id]
    instance_role       = aws_iam_instance_profile.batch_ecs.arn
    bid_percentage      = 70
  }
}

resource "aws_batch_job_queue" "main" {
  name                 = "orchestrator-job-queue"
  state                = "ENABLED"
  priority             = 1
  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.main.arn
  }
}

# IAM Roles
resource "aws_iam_role" "batch_service" {
  name = "orchestrator-batch-service-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "batch.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "batch_service" {
  role       = aws_iam_role.batch_service.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole"
}

resource "aws_iam_role" "batch_ecs_instance" {
  name = "orchestrator-batch-ecs-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "batch_ecs_instance" {
  role       = aws_iam_role.batch_ecs_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_instance_profile" "batch_ecs" {
  name = "orchestrator-batch-ecs-instance"
  role = aws_iam_role.batch_ecs_instance.name
}

# S3 Bucket
resource "aws_s3_bucket" "data" {
  bucket = "orchestrator-data-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "orchestrator-data"
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Data sources
data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

# Security Groups
resource "aws_security_group" "rds" {
  name   = "orchestrator-rds-sg"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
}

resource "aws_security_group" "redis" {
  name   = "orchestrator-redis-sg"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
}

resource "aws_security_group" "batch" {
  name   = "orchestrator-batch-sg"
  vpc_id = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Outputs
output "rds_endpoint" {
  value       = aws_rds_cluster.orchestrator.endpoint
  description = "RDS cluster endpoint"
}

output "redis_endpoint" {
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
  description = "Redis cluster endpoint"
}

output "s3_bucket" {
  value       = aws_s3_bucket.data.bucket
  description = "S3 data bucket name"
}
