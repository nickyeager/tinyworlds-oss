
"""
Modification Extractor

Extracts game modifications from natural language using pattern matching.
No LLM required - uses regex and keyword matching for common patterns.
"""

import re
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class Modification:
    """A single modification to apply to a game template"""
    type: str           # "player_character", "collectible", "difficulty", "speed", etc.
    action: str         # "change", "increase", "decrease", "add"
    target: Optional[str] = None    # What to change (e.g., "player", "enemy")
    value: Optional[str] = None     # New value (e.g., "ninja", "stars")
    description: str = ""           # Human-readable description


class ModificationExtractor:
    """Extract game modifications from natural language descriptions"""

    # Character/entity patterns
    CHARACTER_PATTERNS = [
        (r'\b(ninja|robot|wizard|knight|alien|astronaut|pirate|zombie)\b', 'player_character'),
        (r'\b(?:player|character)\s+(?:is|as)\s+(?:a\s+)?(\w+)', 'player_character'),
        (r'\b(?:play\s+as|be\s+a)\s+(\w+)', 'player_character'),
    ]

    # Collectible patterns
    COLLECTIBLE_PATTERNS = [
        (r'\b(stars?|gems?|diamonds?|crystals?|hearts?|coins?|points?)\b', 'collectible'),
        (r'\bcollect(?:ing)?\s+(\w+)', 'collectible'),
        (r'\bgather(?:ing)?\s+(\w+)', 'collectible'),
        (r'\bpick\s+up\s+(\w+)', 'collectible'),
    ]

    # Difficulty patterns
    DIFFICULTY_PATTERNS = [
        (r'\b(harder|more\s+difficult|challenging)', 'difficulty_increase'),
        (r'\b(easier|simpler|less\s+difficult)', 'difficulty_decrease'),
        (r'\bfor\s+(kids|children|toddlers)', 'difficulty_decrease'),  # "for kids" = easier
        (r'\b(easy|medium|hard|impossible)\s+(?:mode|difficulty)', 'difficulty_set'),
    ]

    # Speed/parameter patterns
    SPEED_PATTERNS = [
        (r'\b(faster|quicker|speed\s+up)', 'speed_increase'),
        (r'\b(slower|slow\s+down)', 'speed_decrease'),
        (r'\bmake\s+(?:the\s+)?player\s+faster', 'speed_increase'),
        (r'\bhigher\s+jump', 'jump_increase'),
        (r'\blower\s+jump', 'jump_decrease'),
    ]

    # Enemy/obstacle patterns
    ENEMY_PATTERNS = [
        (r'\b(spikes?|enemies|obstacles?|traps?|dangers?)\b', 'enemies'),
        (r'\bavoid(?:ing)?\s+(\w+)', 'obstacle'),
        (r'\bdodge\s+(\w+)', 'obstacle'),
        (r'\bwith\s+enemies', 'enemies'),
    ]

    # Theme/aesthetic patterns
    THEME_PATTERNS = [
        (r'\b(space|ocean|forest|desert|city|dungeon|castle)\s+(?:theme|themed)', 'theme'),
        (r'\b(?:in|set\s+in)\s+(?:a\s+)?(space|ocean|forest|desert|city)', 'theme'),
        (r'\b(space|ocean|forest|desert|city)\s+(?:shooter|game|platformer)', 'theme'),  # "space shooter"
        (r'\b(dark|bright|colorful|retro|pixel|neon)\s+(?:colors?|style)', 'style'),
    ]

    def __init__(self):
        """Initialize the modification extractor"""
        pass

    def extract(self, text: str) -> List[Modification]:
        """
        Extract modifications from natural language text

        Args:
            text: Natural language description (e.g., "ninja jumping game with stars")

        Returns:
            List of Modification objects

        Example:
            >>> extractor = ModificationExtractor()
            >>> mods = extractor.extract("ninja jumping game with stars")
            >>> print(mods)
            [
                Modification(type='player_character', action='change', value='ninja'),
                Modification(type='collectible', action='change', value='stars')
            ]
        """
        text_lower = text.lower()
        modifications = []

        # Extract character modifications
        for pattern, mod_type in self.CHARACTER_PATTERNS:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                if match:  # Skip empty matches
                    modifications.append(Modification(
                        type=mod_type,
                        action='change',
                        value=match,
                        description=f"Change player character to {match}"
                    ))
                    break  # Only take first character match

        # Extract collectible modifications
        for pattern, mod_type in self.COLLECTIBLE_PATTERNS:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                if match and match not in ['collecting', 'gathering']:  # Skip gerunds
                    modifications.append(Modification(
                        type=mod_type,
                        action='change',
                        value=match.rstrip('s'),  # Singularize (simple approach)
                        description=f"Change collectibles to {match}"
                    ))
                    break  # Only take first collectible match

        # Extract difficulty modifications
        for pattern, mod_type in self.DIFFICULTY_PATTERNS:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                if match:
                    action = 'increase' if 'increase' in mod_type else \
                            'decrease' if 'decrease' in mod_type else 'set'
                    modifications.append(Modification(
                        type='difficulty',
                        action=action,
                        value=match if action == 'set' else None,
                        description=f"{action.capitalize()} difficulty"
                    ))
                    break

        # Extract speed modifications
        for pattern, mod_type in self.SPEED_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                if 'speed' in mod_type:
                    action = 'increase' if 'increase' in mod_type else 'decrease'
                    modifications.append(Modification(
                        type='speed',
                        action=action,
                        description=f"{action.capitalize()} movement speed"
                    ))
                elif 'jump' in mod_type:
                    action = 'increase' if 'increase' in mod_type else 'decrease'
                    modifications.append(Modification(
                        type='jump_height',
                        action=action,
                        description=f"{action.capitalize()} jump height"
                    ))
                break

        # Extract enemy/obstacle modifications
        for pattern, mod_type in self.ENEMY_PATTERNS:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                if match and match not in ['avoiding', 'dodging']:
                    modifications.append(Modification(
                        type=mod_type,
                        action='change',
                        value=match.rstrip('s'),
                        description=f"Add {match} as obstacles"
                    ))
                    break

        # Extract theme modifications
        for pattern, mod_type in self.THEME_PATTERNS:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                if match:
                    modifications.append(Modification(
                        type=mod_type,
                        action='change',
                        value=match,
                        description=f"Apply {match} theme/style"
                    ))
                    break

        # Remove duplicates (keep first occurrence)
        seen = set()
        unique_mods = []
        for mod in modifications:
            key = (mod.type, mod.value)
            if key not in seen:
                seen.add(key)
                unique_mods.append(mod)

        return unique_mods

    def to_dict(self, modifications: List[Modification]) -> List[Dict]:
        """Convert modifications to dictionary format"""
        return [
            {
                'type': mod.type,
                'action': mod.action,
                'target': mod.target,
                'value': mod.value,
                'description': mod.description
            }
            for mod in modifications
        ]


if __name__ == "__main__":
    # Test the extractor
    extractor = ModificationExtractor()

    test_cases = [
        "ninja jumping game with stars",
        "I want a wizard collecting gems",
        "make a platformer but harder",
        "puzzle game with easier difficulty",
        "robot game in space theme",
        "avoid spikes and collect coins",
        "make the player faster",
        "knight game with higher jump",
    ]

    print("Modification Extractor Test")
    print("=" * 60)

    for text in test_cases:
        print(f"\nInput: '{text}'")
        mods = extractor.extract(text)
        if mods:
            print("Extracted modifications:")
            for mod in mods:
                print(f"  - {mod.description}")
        else:
            print("  No modifications extracted")

    print("\n" + "=" * 60)
