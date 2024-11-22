from strategy.method import Strategy
from common.message import *
from tools.tool import clean_and_split_reply, clean_and_split_reply_list, clean_and_split_titles, clean_and_split_title_list
from tools.filter import *
from tqdm import tqdm
from tools.filter import answers_filter
from tools.tool import read_file
import random
import os
import re
import jieba
from loguru import logger

class backtranslation_rewrite(Strategy):
    def __init__(self, api):
        super().__init__(api)
    
    async def run(self,config, num_question_per_title=10, concurrent_api_requests_num=1):
        main_theme = config.main_theme
        if(config.file_folder):
            file_paths = [f for f in os.listdir(config.file_folder) if f.endswith('.md') or f.endswith('.txt')]
        else:
            file_paths = [config.file_path]
        all_questions = []
        all_answers = []
        for file_path in file_paths:
            text = read_file(file_path)        
            titles = self.genTitle(text,main_theme)
            titles = await self.splitTitles(titles,concurrent_api_requests_num)
            print('-----------titles----------------')
            print(titles)
            
            questions,factlist,extraction2questions = await getFactlist(self,text,titles,main_theme,concurrent_api_requests_num)
            answers = await get_answer(self,questions,text,concurrent_api_requests_num)
            answers,idxs_to_remove = answers_filter(answers)
            questions = [q for idx,q in enumerate(questions) if idx not in idxs_to_remove]

            all_questions.extend(questions)
            all_answers.extend(answers)
        all_answers = await rewrite_QA(self,all_questions,all_answers,text,concurrent_api_requests_num)

        all_answers,idxs_to_remove = answers_filter(all_answers)
        all_questions = [q for idx,q in enumerate(all_questions) if idx not in idxs_to_remove]
        
        return all_questions,all_answers

    def genTitle(self, text, main_theme):
        prompt = buildMessages([
            UserMessage(f"{text}\n根据以上文本提取与{main_theme}相关的具有概括性的若干个小标题。小标题必须包含准确的信息，例如准确的时间、地点、人物、名称、事件等，不能有歧义，不能指向模糊。每个小标题一行，不要有重复.")
        ])            
        titles = clean_and_split_titles(self.api.chat(prompt))
        print('--------titles------------')
        print(titles)
        return titles
    
    async def splitTitles(self, titles, concurrent_api_requests_num=1):
        splitTitles = []
        for idx in tqdm(range(0, len(titles), concurrent_api_requests_num), desc='Splitting titles'):
            batch_titles = titles[idx:idx+concurrent_api_requests_num]
            prompts = []
            for i in range(len(batch_titles)):
                prompt = buildMessages([
                    SystemMessage(
                        "你是一个擅长划分标题的助手。以下是一个标题,该标题可能包含多个事实，不够简洁。对于包含多个事实的标题你需要将该标题划分为多个小标题,每个小标题要包含原标题中的核心信息和一部分有效信息，不能改变原意，每个小标题一行。对于已经足够简洁的标题，则输出原标题。"    
                    ),
                    UserMessage(
                        f"""标题: {batch_titles[i]}\n 只输出划分后的小标题或者原标题"""
                    )
                ])
                prompts.append(prompt)
            titles = await self.api.async_chat(prompts)
            titles = clean_and_split_title_list(titles)
            print('-----------splitTitles----------------')
            print(titles)
            splitTitles.extend(titles)
        splitTitles = list(set(splitTitles))
        return splitTitles
    
    
async def getFactlist(self, text, titles, main_theme, concurrent_api_requests_num=1):
    extraction2questions = []
    factlist = []
    questions = []
    meaningless_symbols = [' ', '，', '。', '、', '：', '；', '“', '”', '‘', '’', '(', ')', '（', '）', '《', '》', '【', '】', '!', '！', '?', '？', '——', '……']
    for idx in tqdm(range(0, len(titles), concurrent_api_requests_num), desc='Processing titles'):
        batch_titles = titles[idx:idx+concurrent_api_requests_num]
        batch_prompts = []
        
        for title in batch_titles:
            prompt = buildMessages(
                [
                UserMessage(f"""
作为一个AI阅读理解助手，你将在下列给定文本中，提取5条与给定标题相关的关键信息
文本: {text}
标题: {title}
你必须严格遵循以下规则：
1.每条关键信息必须与标题{title}相关，包含标题{title}相关的信息。每条关键信息一行。
2.每条关键信息必须包括{main_theme}相关字样。
格式示例：
关键1：
关键2：
关键3："""
)
                ]
)
            batch_prompts.append(prompt)
        batch_extractions = await self.api.async_chat(batch_prompts)
        print('-----------batch_extractions----------------')
        print(batch_extractions)
        for title, extractions_text in zip(batch_titles, batch_extractions):
            titleset = jieba.cut_for_search(title)
            titleset = list(";".join(titleset).split(';'))
            titleset = [t for t in titleset if t not in meaningless_symbols]
            titleset = [t for t in titleset if len(t) >= 3 and len(t) <= 30]
            
            main_theme_set = jieba.cut_for_search(main_theme)
            main_theme_set = list(";".join(main_theme_set).split(';'))
            
            pattern = r'(关键\d+[: 、,：\n]?)(.*?)(?=关键\d+[: 、,：\n]?|\Z)'
            matches = re.findall(pattern, extractions_text, re.S)
            extractions = [match[1].strip() for match in matches]
            extractions = [e for e in extractions if(any(theme in e for theme in (main_theme_set+titleset)))]
            
#             extractionsstr = "\n".join(f"关键{i+1}:{k}" for i, k in enumerate(extractions))
#             prompt = buildMessages(
#                 [
#                 UserMessage(f"""
# 作为一个AI阅读理解助手，你将在下列所给文本中，提取与所给标题相关的关键信息。
# 文本: {text}
# 标题: {title}
# 你必须严格遵循以下规则：
# 1.每条关键信息必须与标题{title}相关，包含标题{title}相关的信息。每条关键信息一行。
# 2.每条关键信息必须包括{main_theme}相关字样。
# 已提取的关键信息有：
# {extractionsstr}
# 生成的关键信息不要与已提取的关键信息重复。""")
#                 ]
#             )
            
#             new_extraction = (await self.api.async_chat([prompt]))[0]
#             new_matches = re.findall(pattern, new_extraction, re.S)
#             new_facts = [match[1].strip() for match in new_matches]
#             new_facts = [e for e in new_facts if(any(theme in e for theme in (main_theme_set+titleset)))]
#             new_facts = [l for l in new_facts if len(l) > 7]
#             print('-----------new_facts----------------')
#             print(new_facts)
#             extractions.extend(new_facts)
#             extractions = list(set(extractions))
            print('-----------extractions----------------')
            print(extractions)
            print("generating questions from extractions")
            for ext_idx in range(0, len(extractions), concurrent_api_requests_num):
                batch_extractions = extractions[ext_idx:ext_idx+concurrent_api_requests_num]
                question_prompts = []
                
                for extraction in batch_extractions:
                    prompt = buildMessages(
                    [
                        UserMessage(f"""
请基于以下事实，生成5个清晰且能够依据该事实清晰正确回答的问题。
事实:{extraction}
每个问题占一行。禁止使用模糊的指代词(如"这个","那个","它",'这次','这天'等)。问题必须包含事实中的关键细节以及关键信息（如具体的名称、时间、地点、事件等），以避免提问模糊或不清晰。"""
                    )
                    ]
                    )
                    question_prompts.append(prompt)
                
                batch_gen_questions = await self.api.async_chat(question_prompts)
                print('-----------batch_gen_questions----------------')
                print(batch_gen_questions)
                for extraction, gen_questions in zip(batch_extractions, batch_gen_questions):
                    gen_questions = gen_questions.split('\n')
                    gen_questions = [re.sub(r'^\d+\.', '', l) for l in gen_questions]
                    gen_questions = [l.strip() for l in gen_questions if len(l) > 5]
                    
                    valid_questions = []
                    for q_idx in range(0, len(gen_questions), concurrent_api_requests_num):
                        batch_questions = gen_questions[q_idx:q_idx+concurrent_api_requests_num]
                        validation_prompts = []
                        
                        for q in batch_questions:
                            prompt = buildMessages([
                                UserMessage(f"""
请判断下列问题是否是无效提问，无效提问的特征如下：
1.非疑问句，包含提问以外的答案、回答、转述原文、错误信息、自言自语、道歉等无意义信息。
2.问题逻辑不通顺，提问方式不自然, 自相矛盾。出现了"文本","根据文本"等字样。
3.提问风格、提问重点或表达方式奇怪，与人类习惯有明显差异。
4.指代不明，问题中包含了指向不明的代词，如"这个"、"那个"、"它"、"本次"、"今天"等。
具有以上任一特征的都会被视为无效提问。
问题:{q}
请先给出简要的打分理由，然后在最后一行输出判断'【无效】'或'【有效】'"""
                            )
                            ]
                                                   )
                            validation_prompts.append(prompt)
                        
                        validation_results = await self.api.async_chat(validation_prompts, temperature=0.7)
                        
                        for q, result in zip(batch_questions, validation_results):
                            if "【有效】" in result.split('\n')[-1]:
                                valid_questions.append(q)
                    
                    if valid_questions:
                        extraction2questions.append({
                            "extraction": extraction,
                            "questions": valid_questions
                        })
                        questions.extend(valid_questions)
    
    return questions, factlist, extraction2questions

async def get_answer(self, questions, text, concurrent_api_requests_num=1):
    answers = []
    for data_idx in tqdm(range(0, len(questions), concurrent_api_requests_num), desc='Processing QA pairs'):
        batch_questions = questions[data_idx:data_idx+concurrent_api_requests_num]

        answer_prompts = []
        for question in batch_questions:
            answer_prompts.append(buildMessages([
                SystemMessage("你是一个对话助手，你擅长从文本中提取信息并且高质量地回答人们的问题。"),
                UserMessage(f"""文本：{text} 问题:\n{question}
请根据文本回答问题。
注意：如果问题指代不明，例如包含('这','他','那次'等)代词，或无法从文本获取答案，则输出"无法回答"。
回答中不要出现'根据文本'，'文本提到','文本中'等字样。""")
            ]))
        
        batch_answers = await self.api.async_chat(answer_prompts)
        answers.extend(batch_answers)
    
    return answers

async def rewrite_QA(self, questions,answers, text, concurrent_api_requests_num=1):
    new_answers = []
    
    for data_idx in tqdm(range(0, len(questions), concurrent_api_requests_num), desc='Rewriting QA pairs'):    
        
        batch_questions = questions[data_idx:data_idx+concurrent_api_requests_num]
        prompts = []
        for q in batch_questions:       
            message = buildMessages([
                SystemMessage("你是一个擅长阅读文本，回答人类问题的AI助手"),
                UserMessage(f"""文本：{text}
问题：{q}
请根据所给文本高质量地回答上述问题，回答应正确、通顺、清晰，据有深度。不应出现"根据文本","文本中"等字眼。"""
                )
            ])
            prompts.append(message)
        answers = await self.api.async_chat(prompts)

        new_answers.extend(answers)

    return new_answers
