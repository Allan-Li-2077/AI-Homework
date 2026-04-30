"""
train_chinese_cls_lstm_multiclass.py
中文"你"字位置分类 —— LSTM 多分类版本

任务：输入一个包含"你"字的五个字的文本，判断"你"在第几位（1-5）
模型：Embedding → LSTM → 取最后隐藏状态 → Linear → Softmax → CrossEntropyLoss
优化：Adam (lr=1e-3)   损失：CrossEntropyLoss   无需 GPU，CPU 即可运行

依赖：torch >= 2.0   (pip install torch)
"""

import random
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# ─── 超参数 ────────────────────────────────────────────────
SEED        = 42
N_SAMPLES   = 4000
MAXLEN      = 5       # 固定5个字
EMBED_DIM   = 64
HIDDEN_DIM  = 64
NUM_CLASSES = 5       # 5分类：位置1-5
LR          = 1e-3
BATCH_SIZE  = 64
EPOCHS      = 20
TRAIN_RATIO = 0.8

random.seed(SEED)
torch.manual_seed(SEED)

# ─── 1. 数据生成 ────────────────────────────────────────────
# 用于生成5个字的文本
CHARS = list('你我他她它们好大中小长短高低快慢新旧美丽帅气聪明笨蛋学生老师朋友家人同学')

def generate_text_with_you_at_position(pos):
    """
    生成包含"你"字的5个字文本，"你"在指定位置(1-5)
    """
    # 生成其他4个位置的字符
    other_chars = random.sample(CHARS, 4)
    # 创建5个字的列表
    text_list = [''] * 5
    # 在指定位置放置"你"
    text_list[pos - 1] = '你'
    # 填充其他位置
    other_idx = 0
    for i in range(5):
        if i != pos - 1:
            text_list[i] = other_chars[other_idx]
            other_idx += 1
    return ''.join(text_list)

def build_dataset(n=N_SAMPLES):
    """生成数据集，标签是"你"字的位置(0-4对应位置1-5)"""
    data = []
    for _ in range(n):
        # 随机选择位置(1-5)
        position = random.randint(1, 5)
        text = generate_text_with_you_at_position(position)
        # 标签是位置-1，因为Python索引从0开始
        label = position - 1
        data.append((text, label))
    random.shuffle(data)
    return data

# ─── 2. 词表构建与编码 ──────────────────────────────────────
def build_vocab(data):
    vocab = {'<PAD>': 0, '<UNK>': 1}
    for sent, _ in data:
        for ch in sent:
            if ch not in vocab:
                vocab[ch] = len(vocab)
    return vocab

def encode(sent, vocab, maxlen=MAXLEN):
    ids  = [vocab.get(ch, 1) for ch in sent]
    ids  = ids[:maxlen]
    ids += [0] * (maxlen - len(ids))
    return ids

# ─── 3. Dataset / DataLoader ────────────────────────────────
class TextDataset(Dataset):
    def __init__(self, data, vocab):
        self.X = [encode(s, vocab) for s, _ in data]
        self.y = [lb for _, lb in data]

    def __len__(self):
        return len(self.y)

    def __getitem__(self, i):
        return (
            torch.tensor(self.X[i], dtype=torch.long),
            torch.tensor(self.y[i], dtype=torch.long),  # 标签为long类型
        )

# ─── 4. 模型定义 ────────────────────────────────────────────
class YouPositionLSTM(nn.Module):
    """
    "你"字位置分类器（LSTM 多分类版）
    架构：Embedding → LSTM → 取最后隐藏状态 → Linear → Softmax → CrossEntropyLoss
    
    LSTM vs RNN 区别：
    - LSTM 有遗忘门、输入门、输出门，能更好地捕捉长距离依赖
    - LSTM 内部维护细胞状态（cell state），信息可以长期保持
    - LSTM 有两个隐藏状态：hidden state (h) 和 cell state (c)
    """
    def __init__(self, vocab_size, embed_dim=EMBED_DIM, hidden_dim=HIDDEN_DIM, 
                 num_classes=NUM_CLASSES, dropout=0.3):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        # LSTM 替代 RNN，返回值包含 (h_n, c_n) 两个隐藏状态
        self.lstm      = nn.LSTM(embed_dim, hidden_dim, batch_first=True)
        self.bn        = nn.BatchNorm1d(hidden_dim)
        self.dropout   = nn.Dropout(dropout)
        self.fc        = nn.Linear(hidden_dim, num_classes)  # 输出num_classes个类别

    def forward(self, x):
        # x: (batch, seq_len)
        # LSTM 返回 (output, (h_n, c_n))
        # output: (B, L, hidden_dim) - 所有时间步的输出
        # h_n: (1, B, hidden_dim) - 最后一个时间步的隐藏状态
        # c_n: (1, B, hidden_dim) - 最后一个时间步的细胞状态
        output, (h_n, c_n) = self.lstm(self.embedding(x))
        
        # 方法1：使用最后一个时间步的输出（等价于取 output[:, -1, :]）
        # 方法2：使用 h_n（最后一个时间步的隐藏状态）
        # 这里使用 output[:, -1, :]，与RNN版本保持一致
        last_hidden = output[:, -1, :]            # (B, hidden_dim)
        last_hidden = self.dropout(self.bn(last_hidden))
        out = self.fc(last_hidden)               # (B, num_classes)
        return out

# ─── 5. 训练与评估 ──────────────────────────────────────────
def evaluate(model, loader):
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for X, y in loader:
            logits  = model(X)
            pred    = logits.argmax(dim=1)  # 取最大值对应的类别
            correct += (pred == y).sum().item()
            total   += len(y)
    return correct / total

def train():
    print("生成数据集...")
    data  = build_dataset(N_SAMPLES)
    vocab = build_vocab(data)
    print(f"  样本数：{len(data)}，词表大小：{len(vocab)}")
    print(f"  分类任务：判断'你'字在5个字文本中的位置(1-5)")
    print(f"  模型架构：LSTM (替代基础RNN)")

    split      = int(len(data) * TRAIN_RATIO)
    train_data = data[:split]
    val_data   = data[split:]

    train_loader = DataLoader(TextDataset(train_data, vocab), batch_size=BATCH_SIZE, shuffle=True)
    val_loader   = DataLoader(TextDataset(val_data,   vocab), batch_size=BATCH_SIZE)

    model     = YouPositionLSTM(vocab_size=len(vocab), num_classes=NUM_CLASSES)
    criterion = nn.CrossEntropyLoss()  # 多分类损失函数
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    total_params = sum(p.numel() for p in model.parameters())
    print(f"  模型参数量：{total_params:,}\n")

    for epoch in range(1, EPOCHS + 1):
        model.train()
        total_loss = 0.0
        for X, y in train_loader:
            logits = model(X)
            loss = criterion(logits, y)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        avg_loss = total_loss / len(train_loader)
        val_acc  = evaluate(model, val_loader)
        print(f"Epoch {epoch:2d}/{EPOCHS}  loss={avg_loss:.4f}  val_acc={val_acc:.4f}")

    print(f"\n最终验证准确率：{evaluate(model, val_loader):.4f}")

    print("\n--- 推理示例 ---")
    model.eval()
    # 测试包含"你"字的5个字文本
    test_cases = [
        '你我他她它',  # 你 在第1位
        '我你他她它',  # 你 在第2位
        '我他你她它',  # 你 在第3位
        '我他她你它',  # 你 在第4位
        '我他她它你',  # 你 在第5位
        '美丽帅气你',  # 你 在第3位（实际测试）
        '聪明笨蛋你',  # 你 在第3位（实际测试）
    ]
    
    with torch.no_grad():
        for sent in test_cases:
            ids   = torch.tensor([encode(sent, vocab)], dtype=torch.long)
            logits = model(ids)
            prob  = torch.softmax(logits, dim=1)
            pred  = logits.argmax(dim=1).item()
            position = pred + 1  # 转换为1-5的位置
            confidence = prob[0][pred].item()
            print(f"  [{position}位(置信度{confidence:.2f})]  {sent}")

if __name__ == '__main__':
    train()
