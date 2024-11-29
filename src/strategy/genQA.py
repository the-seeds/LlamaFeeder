from strategy.method import Strategy
from common.message import *
from tools.tool import *
from tools.filter import *
from tools.tool import read_file
from tqdm import tqdm
from io import StringIO
import asyncio
import logging
import random

logger = logging.getLogger('logger')

class genQA(Strategy):
    def __init__(self,api):
        super().__init__(api)
    
    async def process_single_file(self, config,file_path: str, num_question_per_title: int, concurrent_api_requests_num: int):
        main_theme = config.main_theme
        datas = load_datas(file_path,config) 
        questions = []
        answers = []
        logger.info(f"load data: {datas}")
        for i in range(0,len(datas),concurrent_api_requests_num):
            batch_datas = datas[i:i+concurrent_api_requests_num]
            tasks = []
            for data in batch_datas:
                texts= parse_data(data,config)
                logger.error(f"texts: {texts}")
                for text in texts:
                    if(text == ""):
                        continue
                    task = self.process_single_data(config,text,file_path,main_theme,num_question_per_title,concurrent_api_requests_num)
                    tasks.append(task)
            results = await asyncio.gather(*tasks)
            for question, answer in results:
                questions.extend(question)
                answers.extend(answer)
        return questions, answers
    
    async def process_single_data(self, config,text,file_path: str, main_theme: str, num_question_per_title: int, concurrent_api_requests_num: int,additional_info=""):
        logger.info('='*30 + f'Text of {file_path}' + '='*30)
        logger.info(text[:200])
        logger.info(f"{'=' * 30}Generating Titles For {file_path}{'=' * 30}")
        titles = await self.genTitle(text, main_theme)
        logger.info(f"{'=' * 30}Splitting Titles For {file_path}{'='*30}")
        # titles = await self.splitTitles(titles, concurrent_api_requests_num)
        logger.info(f"{'=' * 30}Titles of {file_path}{'='*30}")
        logger.info(titles)
        logger.info(f"{'=' * 30}Generating Questions For {file_path}{'='*30}")
        questions = await self.generateQuestions(text, main_theme, num_question_per_title, titles, concurrent_api_requests_num=concurrent_api_requests_num,additional_info=additional_info)
        questions = questions_filter(questions)
        logger.info(questions)
        logger.info(f"{'=' * 30}Generating Answers For {file_path}{'='*30}")
        answers = await self.getAnswers(text, questions, concurrent_api_requests_num=concurrent_api_requests_num,main_theme=main_theme)
        answers, idxs_to_remove = answers_filter(answers)
        questions = [q for idx, q in enumerate(questions) if idx not in idxs_to_remove]
        logger.info(f"{'=' * 30}verifying QAs of {file_path}{'='*30}")
        questions,answers = await self.verifyQA(text,questions,answers,concurrent_api_requests_num)
        save_QA_dataset(questions,answers,config.save_dir,config.save_file_name)
        return questions, answers
    
    async def verifyQA(self,text,questions,answers,concurrent_api_requests_num=1):
        prompts = []
        new_questions = []
        new_answers = []
        for i in range(0,len(questions),concurrent_api_requests_num):
            batch_questions = questions[i:i+concurrent_api_requests_num]
            batch_answers = answers[i:i+concurrent_api_requests_num]
            prompts = []
            for q,a in zip(batch_questions,batch_answers):
                prompt = buildMessages(
                    [
                        UserMessage(
                            f"{text}根据文本判断下列问题是否有效以及回答是否正确\n问题: {q}\n答案: {a}\n 只输出'正确'或'错误'，不要有其他信息。"
                            )
                    ]
                )
                prompts.append(prompt)
            replies = await self.api.async_chat(prompts)
            bin = [0 if "错误" in r else 1 for r in replies]
            verified_Q = [q for idx,q in enumerate(batch_questions) if bin[idx] == 1]
            verified_A = [a for idx,a in enumerate(batch_answers) if bin[idx] == 1]
            new_questions.extend(verified_Q)
            new_answers.extend(verified_A)
        return new_questions,new_answers
    
    
    async def run(self, config, num_question_per_title=10, concurrent_api_requests_num=1):
        init_QA_dataset(config.save_dir,config.save_file_name)
        all_questions = []
        all_answers = []
        file_paths = getFilePaths(config.file_folder,config.file_path,config.file_type)
        logger.info(f"{'=' * 30}File Paths{'='*30}")
        logger.info(file_paths)
        tasks = [
            self.process_single_file(
                config,
                file_path,
                num_question_per_title, 
                concurrent_api_requests_num
            )
            for file_path in file_paths
        ]
        concurrent_api_requests_num = 1
        for i in range(0,len(tasks),concurrent_api_requests_num):
            batch_tasks = tasks[i:i+concurrent_api_requests_num]
            results = await asyncio.gather(*batch_tasks)
                    
            for questions, answers in results:
                all_questions.extend(questions)
                all_answers.extend(answers)
            
        return all_questions, all_answers

    async def genTitle(self,text,main_theme):
        prompt = buildMessages(
            [
            SystemMessage(f"你是一个优秀的文本阅读助手，请根据所给文本提取若干个具有针对性的若干个小标题。小标题必须包含具体的准确信息，例如准确的时间、地点、人物、名称、事件等。注意，你所提取的小标题不能指向模糊，不能有歧义。每个小标题一行，不要有重复."),
            UserMessage(f"{text}")
            ]
        )            
        titles = await self.api.async_chat([prompt])
        titles = clean_and_split_title_list(titles)
        return titles
    
    async def splitTitles(self,titles,concurrent_api_requests_num=1):
        splitTitles = []
        for idx in tqdm(range(0,len(titles),concurrent_api_requests_num),desc='Splitting titles'):
            batch_titles = titles[idx:idx+concurrent_api_requests_num]
            prompts = []
            for i in range(len(batch_titles)):
                prompt = buildMessages(
                    [
                        SystemMessage(
                        f"你是一个擅长划分标题的助手。以下是一个标题,该标题可能包含多个事实，不够简洁。对于包含多个事实的标题你需要将该标题划分为多个小标题,每个小标题要包含原标题中的核心信息和一部分有效信息，不能改变原意，每个小标题一行,不输出额外信息。对于已经足够简洁的标题，则输出原标题。"    
                        ),
                        UserMessage(
                            f"""标题: {batch_titles[i]}\n 只输出划分后的小标题或者原标题，不要有其他信息。"""
                        )
                    ]
                )
                prompts.append(prompt)
            titles = await self.api.async_chat(prompts)
            titles = clean_and_split_title_list(titles)
            splitTitles.extend(titles)
        splitTitles = list(set(splitTitles))
        return splitTitles
    
        
    def getPersona(self, text):
        prompt = buildMessages(
            [
                UserMessage(
                    f"根据以下文本：\n{text}生成10个可能对该文本感兴趣的大致人物描述，不能包含人名，每个人物一行"
                )
            ]
        )
        personas = clean_and_split_reply(self.api.chat(prompt))
        return personas
        
    async def generateQuestions(self, text, main_theme, num_question_per_title,titles,concurrent_api_requests_num=1,additional_info=""):
        questions = []
        for idx in tqdm(range(0,len(titles),concurrent_api_requests_num),desc='Generating questions'):
            batch_titles = titles[idx:idx+concurrent_api_requests_num]
            prompts = []
            for i in range(len(batch_titles)):
                prompt = buildMessages(
                    [
                        SystemMessage(f"您是一位航空爱好者。请根据以下内容指向'{main_theme}'提出{num_question_per_title}个您感兴趣的，在不同场景下与“{batch_titles[i]}”有关的问题。问题必须指向'{batch_titles[i]}'。您的问题包含完整名称，事件等完整信息以避免模糊，严禁使用简称。"),
                        UserMessage(
                            f"文本:{text}\n每个问题一行，以数字加'. '开始，不能重复。"
                        ),
                        # SystemMessage(f"你是一名{main_theme}的乘客，请根据以下文件提出{num_question_per_title}个您可能感兴趣的，在不同场景下与“{batch_titles[i]}”有关的问题"),
                        # UserMessage(
                        #     f"根据以下文本：\n" + text + f"指向{main_theme}生成{num_question_per_title}个在不同场景下与“{batch_titles[i]}”有关的可以根据文本内容回答的问题，问题必须明确指向{main_theme}以避免指向模糊"
                        #     f"问题中必须包含{main_theme}字样，问题中不能出现'根据文本内容','根据文本','根据以上文本'等字样，每个问题一行，以数字加'. '开始，不能重复"
                        # ),
                        
                    ]
                )
                logger.info(f"{'-'*20}Prompt of {batch_titles[i]}{'-'*20}")
                logger.info(prompt)
                prompts.append(prompt)
            genQuestions = await self.api.async_chat(prompts)
            logger.info(f"{'-' * 20}Questions of {batch_titles[i]}{'-'*20}")
            logger.info(genQuestions)
            genQuestions = clean_and_split_reply_list(genQuestions)
            questions.extend(genQuestions)
            prompts = []
            # for i in range(len(batch_titles)):
            #     prompt = buildMessages(
            #         [
                        
            #             SystemMessage(f"请根据以下文本内容指向{main_theme}提出{num_question_per_title}个您可能感兴趣的，在不同场景下不含“{i}”但需要结合文本中关于{batch_titles[i]}的知识才能回答的问题"),
            #             UserMessage(
            #                 f"文本:{text}\n每个问题一行，以数字加'. '开始，不能重复。问题中必须明确指向{main_theme}的内容,包含其中的字样。"
            #             ),
            #             # UserMessage(
            #             #     f"请根据以下文本内容{text}指向{main_theme}提出{num_question_per_title}个您可能感兴趣的在不同场景下不含“{i}”但需要结合文本中关于{batch_titles[i]}的知识才能回答的问题，每个问题一行，以数字加”.“开始，不能重复"
            #             #     f"问题中必须明确指向{main_theme}，问题中不能出现'根据文本内容','根据文本','根据以上文本'等字样，每个问题一行，以数字加'. '开始，不能重复"
            #             # )
            #         ]
            #     )
            #     prompts.append(prompt)
            # genQuestions = await self.api.async_chat(prompts)
            # genQuestions = clean_and_split_reply_list(genQuestions)
            # logger.info('-----------Questions----------------')
            # logger.info(genQuestions)
            # questions.extend(genQuestions)
        return questions
    
    async def getAnswers(self, text,questions,concurrent_api_requests_num=1,main_theme=""):
        logger.info("======================Generating Answers======================")
        style= ["热情","细致","专业","友好","简略","幽默"]
        answers = []
        for idx in tqdm(range(0,len(questions),concurrent_api_requests_num),desc="Generating answers"):
            batch_questions = questions[idx:idx+concurrent_api_requests_num]
            prompts=  []
            for i in range(len(batch_questions)):
                prompt = buildMessages(
                    [
                        SystemMessage(f"{text}\n你是一位AI助手，请礼貌、{random.choice(style)}地回复以下问题。对于无法回答的问题，请回复'无法回答'"),
                        UserMessage(
                            f"{batch_questions[i]}"
                        )
                    ]
                )
                prompts.append(prompt)
            
            genAnswers = await self.api.async_chat(prompts)
            for q,a in zip(batch_questions,genAnswers):
                logger.info(f"{'-'*20}QA pair{'-'*20}")
                logger.info(f"{'-'*15}Question{'-'*15}")
                logger.info(f"{q}")
                logger.info(f"{'-'*15}Answer{'-'*15}")
                logger.info(f"{a}")
            answers.extend(genAnswers)
        return answers