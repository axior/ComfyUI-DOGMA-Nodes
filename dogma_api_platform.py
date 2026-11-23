"""DOGMA API Platform: additive, frontend-only launcher for native partner nodes."""


class DOGMAAPIPlatformV1:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"config": ("STRING", {"default": "{}", "multiline": True})}}

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "settings"
    CATEGORY = "DOGMA/API Platform"
    DESCRIPTION = "Open DOGMA API Platform. Generation uses the existing Comfy partner API nodes."

    def settings(self, config):
        return {"ui": {"text": ["Apri DOGMA / API Platform e usa Run nel pannello."]}, "result": ()}


NODE_CLASS_MAPPINGS = {"DOGMAAPIPlatformV1": DOGMAAPIPlatformV1}
NODE_DISPLAY_NAME_MAPPINGS = {"DOGMAAPIPlatformV1": "DOGMA / API Platform"}
