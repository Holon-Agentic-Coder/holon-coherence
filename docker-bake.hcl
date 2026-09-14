variable "CI" {
  default = "false"
}

target "common" {
  context = "."
  dockerfile = "Dockerfile"
  cache-from = CI == "true" ? ["type=gha,scope=holon-coherence"] : []
  cache-to = CI == "true" ? ["type=gha,mode=max,scope=holon-coherence"] : []
}

target "coherence" {
  inherits = ["common"]
  tags = [
    "holon-coherence:latest",
    "ghcr.io/holon-agentic-coder/holon-coherence:latest"
  ]
}

group "default" {
  targets = ["coherence"]
}
