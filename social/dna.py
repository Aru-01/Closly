"""
Backward-compatibility facade for Style DNA matching service.
Logic has been modularized into social.services.dna_services.
"""
from social.services.dna_services import calculate_dna_match

__all__ = ['calculate_dna_match']
