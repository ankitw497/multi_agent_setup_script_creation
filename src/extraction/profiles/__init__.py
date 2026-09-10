"""Pluggable extraction profiles (plan §6.1). New profiles are added here as
config/code, never by hard-coding a new markup family into html_parser.py."""
from .base import ExtractionProfile
from .generic import GenericProfile
from .guide import GuideProfile
from .video_script import VideoScriptProfile

ALL_PROFILES: list[ExtractionProfile] = [GuideProfile(), VideoScriptProfile()]
FALLBACK_PROFILE: ExtractionProfile = GenericProfile()

__all__ = ["ALL_PROFILES", "FALLBACK_PROFILE", "ExtractionProfile",
           "GuideProfile", "VideoScriptProfile", "GenericProfile"]
