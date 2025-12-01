from data_transformer import DataTransformer

# 加载 SFT 数据
# dt = DataTransformer.load("data/sft_dataset_example.jsonl")

# 或者从通用数据转换为 SFT 格式
dt = DataTransformer.load("data/data.jsonl")
sft_data = dt.to_sft(style="messages")

# 保存为 SFT 格式
dt.save("output_sft.jsonl", format_type="sft")