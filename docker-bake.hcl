variable "DOCKERHUB_REPO" {
  default = "humanik"
}

variable "DOCKERHUB_IMG" {
  default = "gemma-vllm-worker"
}

variable "RELEASE_VERSION" {
  default = "latest"
}

variable "HUGGINGFACE_ACCESS_TOKEN" {
  default = ""
}

group "default" {
  targets = ["gemma-worker"]
}

target "gemma-worker" {
  tags = ["${DOCKERHUB_REPO}/${DOCKERHUB_IMG}:${RELEASE_VERSION}"]
  context = "."
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64"]
}
