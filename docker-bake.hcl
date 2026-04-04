variable "REGISTRY" {
  default = "ghcr.io"
}

variable "IMAGE_NAME" {
  default = "humanikio/gemmavllmworker"
}

variable "RELEASE_VERSION" {
  default = "latest"
}

group "default" {
  targets = ["gemma-worker"]
}

target "gemma-worker" {
  tags = ["${REGISTRY}/${IMAGE_NAME}:${RELEASE_VERSION}"]
  context = "."
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
}
