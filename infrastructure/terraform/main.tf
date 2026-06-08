terraform {
  required_version = ">= 1.6.0"
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

variable "gameops_image" {
  description = "GameOps Center image tag."
  type        = string
  default     = "gameops-center:local"
}

resource "docker_network" "gameops" {
  name = "gameops-net"
}

resource "docker_volume" "gameops_data" {
  name = "gameops-mysql-data"
}

resource "docker_container" "mysql" {
  name  = "gameops-mysql"
  image = "mysql:8.4"

  networks_advanced {
    name = docker_network.gameops.name
  }

  ports {
    internal = 3306
    external = 3306
  }

  env = [
    "MYSQL_DATABASE=gameops",
    "MYSQL_USER=gameops",
    "MYSQL_PASSWORD=gameops-pass",
    "MYSQL_ROOT_PASSWORD=root-pass"
  ]

  volumes {
    volume_name    = docker_volume.gameops_data.name
    container_path = "/var/lib/mysql"
  }
}

resource "docker_container" "gameops_center" {
  name  = "gameops-center"
  image = var.gameops_image
  depends_on = [docker_container.mysql]

  networks_advanced {
    name = docker_network.gameops.name
  }

  ports {
    internal = 8018
    external = 8018
  }

  env = [
    "GAMEOPS_MYSQL_HOST=gameops-mysql",
    "GAMEOPS_MYSQL_PORT=3306",
    "GAMEOPS_MYSQL_DATABASE=gameops",
    "GAMEOPS_MYSQL_USER=gameops",
    "GAMEOPS_MYSQL_PASSWORD=gameops-pass",
    "GAMEOPS_HOST=0.0.0.0",
    "GAMEOPS_RUNTIME=docker",
    "GAMEOPS_DRY_RUN=true"
  ]
}

output "gameops_url" {
  value = "http://127.0.0.1:8018"
}
