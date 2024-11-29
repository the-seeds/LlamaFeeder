import json
from typing import List, Union, Dict
import re
import os
from pathlib import Path
import logging

logger = logging.getLogger("logger")
def read_file(file_path:str)-> str:
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def load_datas(file_path,config):
    with open(file_path, 'r', encoding='utf-8') as file:
        if config.is_structure_data:
            return json.load(file)
        else:
            texts = file.read()
            textsList = [texts[i:i+4000] for i in range(0, len(texts), 4000)]
            return textsList

def parse_data(raw_data, config):
    """
    raw_data: str or dict
    return: list[str]
    """
    if not config.is_structure_data:
        return [raw_data]

    try:
        structured_data = load_json(raw_data)
        if not structured_data:
            return [raw_data]
            
        formatted_text = format_structured_data(
            structured_data,
            config.text_template
        )
        return [formatted_text]
        
    except Exception as e:
        raise Exception(f"Error: {e}")

def write_json_file(file_path:str, dataset:List[dict]):
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(dataset, file, ensure_ascii=False, indent=2)
        
def format_structured_data(data: Dict, template: str) -> str:
    try:
        formatted_data = {}
        for key, value in data.items():
            if isinstance(value, list):
                formatted_data[key] = '、'.join(str(v) for v in value)
            else:
                formatted_data[key] = value            
        return template.format(**formatted_data)
    except KeyError as e:
        raise KeyError(f"Template missing key: {str(e)}")
    except Exception as e:
        raise Exception(f"Error: {e}")

def load_json(data: Union[str, Dict]) -> Dict:
    if isinstance(data, dict):
        return data        
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return {}        

def clean_and_split_reply(lines:str)-> List[str]:
    lines = lines.split('\n')
    lines = [l.strip(".#`\\\"\' ") for l in lines]
    lines = [re.sub(r'^[ :：\.、,\'\"]?\d+[ :：\.、]', '', l) for l in lines]
    lines = [l for l in lines if len(l) > 10]
    return lines

def clean_and_split_reply_list(replys:List[str])-> List[str]:
    cleaned =[]
    for reply in replys: 
        reply = clean_and_split_reply(reply)
        cleaned.extend(reply)
    return cleaned

def clean_and_split_titles(titles:str)-> List[str]:
    titles = titles.split('\n')
    titles = [re.sub(r'^[ :：\.、]?(\d+)[ :：\.、]', '', l) for l in titles]
    titles = [re.sub(r'^([小]?标题)[ :：\.、\d]?', '', l) for l in titles]
    titles = [l.strip() for l in titles]
    titles = [l for l in titles if len(l) >= 3]
    return titles

def clean_and_split_title_list(titlelist:List[str])->List[str]:
    cleaned =[]
    for title in titlelist:
        title = clean_and_split_titles(title)        
        cleaned.extend(title)
    return cleaned
    
    
def save_QA_dataset(questions,answers,save_dir,name):
    dataset = []
    for q,a in zip(questions,answers):
        dataset.append(
            {"instruction":q,
             "input":"",
             "output":a             
             })
    path = f"{save_dir}/{name}"
    write_json_file(path,dataset)
    print(f"dataset with {len(dataset)} samples saved to {path}")
    
def getFilePaths(folder,file,file_type:list[str]):
    paths = []
    if(folder):
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.split('.')[-1] in file_type:
                    paths.append(Path(root,file))
    else:
        paths.append(file)
    return paths

def init_QA_dataset(save_dir,name):
    datas = []
    path = f"{save_dir}/{name}"
    if not os.path.exists(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(datas, file, ensure_ascii=False, indent=2)