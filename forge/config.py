"""Configuration for BELENTANI FORGE."""
import os
from pathlib import Path

HOME = Path.home()
FORGE_HOME = Path(os.environ.get("FORGE_HOME", HOME / ".forge"))
FORGE_HOME.mkdir(parents=True, exist_ok=True)
REPORTS_DIR = FORGE_HOME / "reports"
MANIFESTS_DIR = FORGE_HOME / "manifests"
LOGS_DIR = FORGE_HOME / "logs"
SCAN_LOCAL = FORGE_HOME / "scan_local.json"
SCAN_GITHUB = FORGE_HOME / "scan_github.json"

for d in [REPORTS_DIR, MANIFESTS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

GITHUB_USER = os.environ.get("FORGE_GH_USER", "belentani7")
GITHUB_URL = f"https://github.com/{GITHUB_USER}"

FROZEN_FRONTEND = {
    "ManosAbiertas", "manos-abiertas",
    "linguaforge", "LinguaForge",
    "secure-t", "Secure-T",
    "open-school", "Open-School",
    "aion", "AION",
}

CATEGORY_PATTERNS = {
    "CORE": ["belentani7", "Belentani", "belentani-web", "belentani_Omega",
             "belentani-Omega", "belentani-omega", "belentaniexperience",
             "belentani-studio", "NOIACORE", "noiacore"],
    "FULLSTACK": ["FULLSTACK", "BUILDAI", "JUDAS", "judas"],
    "PRODUCTS": ["linguaforge", "ManosAbiertas", "Oculus", "arte", "ArteQueVeste",
                 "Cruzando", "nataliamarinho", "manos-abiertas"],
    "AION_AGENTS": ["aion", "AION", "nexus", "omniagent", "llm-vfx",
                     "local-agent", "open-manus", "CENTRO-MANUS", "agentbox",
                     "agentguard"],
    "DUCK": ["duck", "Duck", "DUCK", "heyduck"],
    "SKILLS": ["claude-skills", "manus-ai-skill", "meta-skill", "MetaSkill",
               "mimocode", "DEV-TOOLKIT", "caveman", "safe-exec", "forja",
               "proofmesh", "registro-proyectos"],
    "AI_COMPUTE": ["qwencloud", "comfyui", "gpu-cost", "latent-consistency",
                    "pbr-validator", "temporal-artifact", "oss-compass",
                    "decision-atlas", "failure-atlas"],
    "VOICE": ["voice-ai", "voice-bot", "VOICE-LAB"],
    "DOCS_BOOKS": ["LIBRO", "libro"],
    "INFRASTRUCTURE": ["skills-registry", "pvc-u", "control-linux",
                        "linux-power", "nebula-cosmos", "la-alquitara"],
}
