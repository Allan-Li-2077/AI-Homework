## 这个文件里有

.cache

1_Pooling

.gitattributes

config.json

config_sentence_transformers.json

model.safetensors

modules.json

pytorch_model.bin

README.md

sentence_bert_config.json

special_tokens_map.json

tokenizer.json

tokenizer_config.json

vocab.txt

## bge-small-zh-v1.5 模型目录：

1.pytorch_model.bin / model.safetensors：模型权重文件（二选一即可加载，safetensors 更安全）

2.vocab.txt、tokenizer.json、tokenizer_config.json：分词器配置

3.config.json：主干 Transformer 模型配置

4.sentence_bert_config.json、config_sentence_transformers.json：Sentence-Transformers 向量模型专用配置

5.1_Pooling：池化层配置文件夹，BGE 向量模型必须依靠它生成句向量

6..cache、.gitattributes：版本控制缓存文件，运行代码时不用管

7.加载代码识别标准：SentenceTransformer 会自动读取这套文件，完美适配 RAG 知识库检索功能。
