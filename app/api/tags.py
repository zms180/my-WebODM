from rest_framework import serializers
import json

class TagsField(serializers.JSONField):
    def to_representation(self, tags):
        return [t for t in tags.split(" ") if t != ""]

    def to_internal_value(self, tags):
        if isinstance(tags, str):
            return tags.strip()
        return " ".join([t.strip() for t in tags])

def parse_tags_input(tags):
    if tags is None:
        return []
    
    if isinstance(tags, str):
        try:
            r = json.loads(tags)
            if isinstance(r, list):
                return r
            elif isinstance(r, str):
                return [r]
            else:
                raise Exception("Invalid tags string")
        except:
            tag = tags.strip()
            return [tag] if tag else []
    elif isinstance(tags, list):
        return list(map(str, tags))
    else:
        return []
