def read_json(filepath:str):
    import json
    with open(filepath,'r',encoding='utf-8') as f:
        return json.load(f)