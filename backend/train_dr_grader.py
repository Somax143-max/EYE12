import os
import random
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import cv2

torch.manual_seed(42)
np.random.seed(42)
random.seed(42)

# --- 1. SQUEEZE-AND-EXCITATION RESIDUAL DR GRADER ARCHITECTURE ---
class SEBlock(nn.Module):
    def __init__(self, channels, reduction=16):
        super(SEBlock, self).__init__()
        self.fc1 = nn.Linear(channels, max(channels // reduction, 8))
        self.relu = nn.ReLU(inplace=True)
        self.fc2 = nn.Linear(max(channels // reduction, 8), channels)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        b, c, _, _ = x.size()
        y = x.view(b, c, -1).mean(dim=2)
        y = self.fc1(y)
        y = self.relu(y)
        y = self.fc2(y)
        y = self.sigmoid(y).view(b, c, 1, 1)
        return x * y

class ResBlock(nn.Module):
    def __init__(self, in_channels, out_channels, stride=1):
        super(ResBlock, self).__init__()
        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size=3, stride=stride, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.relu = nn.LeakyReLU(0.1, inplace=True)
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=1, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.se = SEBlock(out_channels)
        
        self.shortcut = nn.Sequential()
        if stride != 1 or in_channels != out_channels:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(out_channels)
            )

    def forward(self, x):
        res = self.shortcut(x)
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)
        out = self.conv2(out)
        out = self.bn2(out)
        out = self.se(out)
        out += res
        return self.relu(out)

class RetinaDRGradingNet(nn.Module):
    def __init__(self):
        super(RetinaDRGradingNet, self).__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=7, stride=2, padding=3, bias=False),
            nn.BatchNorm2d(32),
            nn.LeakyReLU(0.1, inplace=True),
            nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
        )
        self.layer1 = nn.Sequential(ResBlock(32, 64, stride=1), ResBlock(64, 64, stride=1))
        self.layer2 = nn.Sequential(ResBlock(64, 128, stride=2), ResBlock(128, 128, stride=1))
        self.layer3 = nn.Sequential(ResBlock(128, 256, stride=2), ResBlock(256, 256, stride=1))
        self.layer4 = nn.Sequential(ResBlock(256, 512, stride=2), ResBlock(512, 512, stride=1))
        
        self.pool = nn.AdaptiveAvgPool2d((1, 1))
        
        # Head 1: 5-Class ICDR Grade
        self.grade_head = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.3),
            nn.Linear(512, 128),
            nn.BatchNorm1d(128),
            nn.LeakyReLU(0.1, inplace=True),
            nn.Dropout(0.2),
            nn.Linear(128, 5)
        )
        
        # Head 2: Continuous Percentage (0.0 to 1.0)
        self.percent_head = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.3),
            nn.Linear(512, 64),
            nn.BatchNorm1d(64),
            nn.LeakyReLU(0.1, inplace=True),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )

    def forward(self, x):
        feat = self.stem(x)
        feat = self.layer1(feat)
        feat = self.layer2(feat)
        feat = self.layer3(feat)
        feat = self.layer4(feat)
        pooled = self.pool(feat)
        grade_logits = self.grade_head(pooled)
        percent = self.percent_head(pooled)
        return grade_logits, percent

# --- 2. RETINAL TRAINING SAMPLES GENERATOR ---
def create_synthetic_fundus(grade=0, w=224, h=224):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cx, cy = w // 2, h // 2
    radius = int(min(w, h) * random.uniform(0.44, 0.48))
    
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
    mask = dist <= radius
    
    base_r = random.randint(160, 225)
    base_g = random.randint(55, 105)
    base_b = random.randint(12, 40)
    
    falloff = np.clip(1.0 - (dist / radius) * random.uniform(0.35, 0.55), 0.2, 1.0)
    img[mask, 2] = np.clip(base_r * falloff[mask] + np.random.normal(0, 3, np.sum(mask)), 0, 255).astype(np.uint8)
    img[mask, 1] = np.clip(base_g * falloff[mask] + np.random.normal(0, 2, np.sum(mask)), 0, 255).astype(np.uint8)
    img[mask, 0] = np.clip(base_b * falloff[mask] + np.random.normal(0, 2, np.sum(mask)), 0, 255).astype(np.uint8)
    
    disc_side = random.choice([-1, 1])
    disc_x = cx + disc_side * int(radius * random.uniform(0.35, 0.55))
    disc_y = cy + random.randint(-12, 12)
    disc_r = int(radius * random.uniform(0.16, 0.22))
    cv2.ellipse(img, (disc_x, disc_y), (disc_r, int(disc_r * 1.25)), random.randint(-15, 15), 0, 360, 
                (random.randint(40, 90), random.randint(180, 230), random.randint(230, 255)), -1)
    cv2.circle(img, (disc_x, disc_y), int(disc_r * 0.5), (random.randint(80, 130), random.randint(210, 250), 255), -1)
    
    fovea_x = cx - disc_side * int(radius * random.uniform(0.2, 0.35))
    fovea_y = disc_y + random.randint(-6, 6)
    cv2.circle(img, (fovea_x, fovea_y), int(disc_r * 0.65), (random.randint(10, 25), random.randint(25, 45), random.randint(65, 100)), -1)
    
    num_trunks = random.randint(6, 12)
    for _ in range(num_trunks):
        curr_x, curr_y = disc_x, disc_y
        angle = random.uniform(-np.pi, np.pi)
        pts = [(curr_x, curr_y)]
        thickness = random.randint(2, 3)
        for _ in range(random.randint(5, 9)):
            step_len = random.randint(14, 25)
            curr_x += int(np.cos(angle) * step_len)
            curr_y += int(np.sin(angle) * step_len)
            pts.append((curr_x, curr_y))
            angle += random.uniform(-0.35, 0.35)
        pts = np.array(pts, np.int32).reshape((-1, 1, 2))
        cv2.polylines(img, [pts], isClosed=False, color=(random.randint(10, 30), random.randint(15, 45), random.randint(50, 110)), thickness=thickness)
        
    if grade == 0:
        percent = random.uniform(0.0, 0.03)
    elif grade == 1:
        percent = random.uniform(0.15, 0.28)
        for _ in range(random.randint(1, 4)):
            ma_x = cx + random.randint(-int(radius*0.6), int(radius*0.6))
            ma_y = cy + random.randint(-int(radius*0.6), int(radius*0.6))
            cv2.circle(img, (ma_x, ma_y), random.randint(1, 2), (10, 15, random.randint(50, 90)), -1)
    elif grade == 2:
        percent = random.uniform(0.40, 0.62)
        for _ in range(random.randint(6, 14)):
            ma_x = cx + random.randint(-int(radius*0.7), int(radius*0.7))
            ma_y = cy + random.randint(-int(radius*0.7), int(radius*0.7))
            cv2.circle(img, (ma_x, ma_y), random.randint(1, 3), (10, 15, random.randint(50, 90)), -1)
        for _ in range(random.randint(2, 6)):
            ex_x = cx + random.randint(-int(radius*0.6), int(radius*0.6))
            ex_y = cy + random.randint(-int(radius*0.6), int(radius*0.6))
            cv2.circle(img, (ex_x, ex_y), random.randint(2, 4), (random.randint(30, 80), random.randint(200, 245), 255), -1)
    elif grade == 3:
        percent = random.uniform(0.75, 0.88)
        for _ in range(random.randint(20, 45)):
            ma_x = cx + random.randint(-int(radius*0.75), int(radius*0.75))
            ma_y = cy + random.randint(-int(radius*0.75), int(radius*0.75))
            cv2.circle(img, (ma_x, ma_y), random.randint(2, 4), (10, 15, random.randint(50, 90)), -1)
        for _ in range(random.randint(12, 35)):
            ex_x = cx + random.randint(-int(radius*0.65), int(radius*0.65))
            ex_y = cy + random.randint(-int(radius*0.65), int(radius*0.65))
            cv2.circle(img, (ex_x, ex_y), random.randint(2, 6), (random.randint(30, 80), random.randint(210, 255), 255), -1)
    else:
        percent = random.uniform(0.92, 0.99)
        for _ in range(random.randint(25, 50)):
            ma_x = cx + random.randint(-int(radius*0.8), int(radius*0.8))
            ma_y = cy + random.randint(-int(radius*0.8), int(radius*0.8))
            cv2.circle(img, (ma_x, ma_y), random.randint(2, 5), (10, 15, random.randint(50, 90)), -1)
        for _ in range(random.randint(3, 7)):
            nv_x, nv_y = disc_x + random.randint(-15, 15), disc_y + random.randint(-15, 15)
            for _ in range(8):
                nx = nv_x + random.randint(-20, 20)
                ny = nv_y + random.randint(-20, 20)
                cv2.line(img, (nv_x, nv_y), (nx, ny), (10, 20, 70), 1)
                nv_x, nv_y = nx, ny
                
    return img, grade, percent

class DRDataset(Dataset):
    def __init__(self, num_samples=1800):
        self.samples = []
        print(f'Generating {num_samples} DR staging samples...')
        
        real_healthy_paths = [
            r'C:/Users/DELL/.gemini/antigravity/brain/83a8594b-73c9-401b-8ba6-024177eb2f1c/.user_uploaded/media_1788899693667.webp',
            r'C:/Users/DELL/.gemini/antigravity/brain/83a8594b-73c9-401b-8ba6-024177eb2f1c/.user_uploaded/media_1788899711092.webp'
        ]
        real_healthy = []
        for p in real_healthy_paths:
            if os.path.exists(p):
                im = cv2.imread(p)
                if im is not None: real_healthy.append(im)
                
        real_dr_path = r'C:/Users/DELL/.gemini/antigravity/brain/83a8594b-73c9-401b-8ba6-024177eb2f1c/.user_uploaded/media_1788888654346.png'
        real_dr = []
        if os.path.exists(real_dr_path):
            im = cv2.imread(real_dr_path)
            if im is not None: real_dr.append(im)
            
        if real_healthy:
            for _ in range(350):
                base = random.choice(real_healthy)
                h_b, w_b = base.shape[:2]
                M = cv2.getRotationMatrix2D((w_b // 2, h_b // 2), random.uniform(-180, 180), random.uniform(0.85, 1.15))
                aug = cv2.warpAffine(base, M, (w_b, h_b), borderMode=cv2.BORDER_REFLECT)
                if random.random() < 0.5: aug = cv2.flip(aug, 1)
                aug = cv2.resize(aug, (224, 224))
                aug = np.clip(aug.astype(np.float32) * random.uniform(0.88, 1.12) + random.randint(-10, 10), 0, 255).astype(np.uint8)
                self.samples.append((aug, 0, random.uniform(0.0, 0.02)))
                
        if real_dr:
            for _ in range(250):
                base = random.choice(real_dr)
                h_b, w_b = base.shape[:2]
                M = cv2.getRotationMatrix2D((w_b // 2, h_b // 2), random.uniform(-180, 180), random.uniform(0.85, 1.15))
                aug = cv2.warpAffine(base, M, (w_b, h_b), borderMode=cv2.BORDER_REFLECT)
                if random.random() < 0.5: aug = cv2.flip(aug, 1)
                aug = cv2.resize(aug, (224, 224))
                aug = np.clip(aug.astype(np.float32) * random.uniform(0.88, 1.12) + random.randint(-10, 10), 0, 255).astype(np.uint8)
                self.samples.append((aug, 3, random.uniform(0.80, 0.88)))
                
        samples_per_grade = 240
        for g in range(5):
            for _ in range(samples_per_grade):
                im, gr, pct = create_synthetic_fundus(grade=g, w=224, h=224)
                self.samples.append((im, gr, pct))
                
        random.shuffle(self.samples)
        print(f'Total DR dataset compiled: {len(self.samples)}')

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        img_bgr, grade, percent = self.samples[idx]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        tensor = torch.from_numpy(img_rgb).permute(2, 0, 1).float() / 255.0
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        tensor = (tensor - mean) / std
        return tensor, torch.tensor(grade, dtype=torch.long), torch.tensor([percent], dtype=torch.float32)

def train_dr_model(epochs=6, batch_size=32, lr=1e-3, save_path='retina_dr_grader.pth'):
    print('Initializing RetinaDRGradingNet Training...')
    dataset = DRDataset(num_samples=1800)
    train_size = int(0.85 * len(dataset))
    val_size = len(dataset) - train_size
    train_set, val_set = torch.utils.data.random_split(dataset, [train_size, val_size])
    
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)
    
    model = RetinaDRGradingNet()
    ce_loss = nn.CrossEntropyLoss()
    mse_loss = nn.MSELoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    
    best_val_acc = 0.0
    
    for epoch in range(1, epochs + 1):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        
        for images, grades, percents in train_loader:
            optimizer.zero_grad()
            grade_logits, pred_pcts = model(images)
            loss1 = ce_loss(grade_logits, grades)
            loss2 = mse_loss(pred_pcts, percents) * 5.0
            loss = loss1 + loss2
            loss.backward()
            optimizer.step()
            
            running_loss += loss.item() * images.size(0)
            _, preds = torch.max(grade_logits, 1)
            correct += (preds == grades).sum().item()
            total += grades.size(0)
            
        scheduler.step()
        train_loss = running_loss / total
        train_acc = (correct / total) * 100.0
        
        model.eval()
        val_correct = 0
        val_total = 0
        val_loss = 0.0
        with torch.no_grad():
            for val_imgs, val_grades, val_pcts in val_loader:
                v_logits, v_pcts = model(val_imgs)
                vl1 = ce_loss(v_logits, val_grades)
                vl2 = mse_loss(v_pcts, val_pcts) * 5.0
                val_loss += (vl1 + vl2).item() * val_imgs.size(0)
                _, val_preds = torch.max(v_logits, 1)
                val_correct += (val_preds == val_grades).sum().item()
                val_total += val_grades.size(0)
                
        val_acc = (val_correct / val_total) * 100.0
        avg_val_loss = val_loss / val_total
        print(f'Epoch [{epoch}/{epochs}] - Train Loss: {train_loss:.4f} | Train Acc: {train_acc:.1f}% | Val Loss: {avg_val_loss:.4f} | Val Acc: {val_acc:.1f}%', flush=True)
        
        if val_acc >= best_val_acc:
            best_val_acc = val_acc
            torch.save(model.state_dict(), save_path)
            
    print(f'DR Grader Training Complete! Best Validation Accuracy: {best_val_acc:.1f}%', flush=True)
    print(f'Saved model weights to {save_path}', flush=True)
    return model

if __name__ == '__main__':
    train_dr_model(epochs=6, batch_size=32, lr=1e-3, save_path='retina_dr_grader.pth')
