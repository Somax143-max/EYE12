import os
import random
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import cv2

# Set random seeds for reproducibility
torch.manual_seed(42)
np.random.seed(42)
random.seed(42)

# --- 1. SQUEEZE-AND-EXCITATION RESIDUAL NETWORK ARCHITECTURE ---
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

class RetinaEyeClassifier(nn.Module):
    def __init__(self):
        super(RetinaEyeClassifier, self).__init__()
        # Stem
        self.stem = nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=7, stride=2, padding=3, bias=False), # 112x112
            nn.BatchNorm2d(32),
            nn.LeakyReLU(0.1, inplace=True),
            nn.MaxPool2d(kernel_size=3, stride=2, padding=1) # 56x56
        )
        
        # Residual stages
        self.layer1 = nn.Sequential(
            ResBlock(32, 64, stride=1),
            ResBlock(64, 64, stride=1)
        )
        self.layer2 = nn.Sequential(
            ResBlock(64, 128, stride=2), # 28x28
            ResBlock(128, 128, stride=1)
        )
        self.layer3 = nn.Sequential(
            ResBlock(128, 256, stride=2), # 14x14
            ResBlock(256, 256, stride=1)
        )
        self.layer4 = nn.Sequential(
            ResBlock(256, 512, stride=2), # 7x7
            ResBlock(512, 512, stride=1)
        )
        
        self.pool = nn.AdaptiveAvgPool2d((1, 1))
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.4),
            nn.Linear(512, 128),
            nn.BatchNorm1d(128),
            nn.LeakyReLU(0.1, inplace=True),
            nn.Dropout(0.3),
            nn.Linear(128, 2) # 0: Non-Eye / Portrait, 1: Authentic Fundus
        )

    def forward(self, x):
        out = self.stem(x)
        out = self.layer1(out)
        out = self.layer2(out)
        out = self.layer3(out)
        out = self.layer4(out)
        out = self.pool(out)
        out = self.classifier(out)
        return out

# --- 2. ADVANCED DATA GENERATORS ---
def create_fundus_sample(w=224, h=224):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cx, cy = w // 2, h // 2
    radius = int(min(w, h) * random.uniform(0.42, 0.48))
    
    Y, X = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((X - cx)**2 + (Y - cy)**2)
    mask = dist_from_center <= radius
    
    base_r = random.randint(155, 235)
    base_g = random.randint(45, 110)
    base_b = random.randint(8, 45)
    
    falloff = np.clip(1.0 - (dist_from_center / radius) * random.uniform(0.35, 0.65), 0.15, 1.0)
    img[mask, 2] = np.clip(base_r * falloff[mask] + np.random.normal(0, 4, np.sum(mask)), 0, 255).astype(np.uint8)
    img[mask, 1] = np.clip(base_g * falloff[mask] + np.random.normal(0, 3, np.sum(mask)), 0, 255).astype(np.uint8)
    img[mask, 0] = np.clip(base_b * falloff[mask] + np.random.normal(0, 2, np.sum(mask)), 0, 255).astype(np.uint8)
    
    if random.random() < 0.25:
        img[~mask] = [random.randint(240, 255), random.randint(240, 255), random.randint(240, 255)]
        
    disc_side = random.choice([-1, 1])
    disc_x = cx + disc_side * int(radius * random.uniform(0.35, 0.55))
    disc_y = cy + random.randint(-15, 15)
    disc_r = int(radius * random.uniform(0.16, 0.24))
    cv2.ellipse(img, (disc_x, disc_y), (disc_r, int(disc_r * 1.25)), random.randint(-15, 15), 0, 360, 
                (random.randint(40, 90), random.randint(180, 230), random.randint(230, 255)), -1)
    cv2.circle(img, (disc_x, disc_y), int(disc_r * 0.5), (random.randint(80, 130), random.randint(210, 250), 255), -1)
    
    fovea_x = cx - disc_side * int(radius * random.uniform(0.2, 0.4))
    fovea_y = disc_y + random.randint(-8, 8)
    cv2.circle(img, (fovea_x, fovea_y), int(disc_r * 0.7), (random.randint(10, 30), random.randint(25, 55), random.randint(65, 110)), -1)
    
    for _ in range(random.randint(8, 16)):
        curr_x, curr_y = disc_x, disc_y
        angle = random.uniform(-np.pi, np.pi)
        pts = [(curr_x, curr_y)]
        thickness = random.randint(2, 4)
        for step in range(random.randint(5, 10)):
            step_len = random.randint(12, 25)
            curr_x += int(np.cos(angle) * step_len)
            curr_y += int(np.sin(angle) * step_len)
            pts.append((curr_x, curr_y))
            angle += random.uniform(-0.35, 0.35)
        pts = np.array(pts, np.int32).reshape((-1, 1, 2))
        cv2.polylines(img, [pts], isClosed=False, color=(random.randint(10, 35), random.randint(15, 50), random.randint(50, 120)), thickness=thickness)
        
    if random.random() < 0.5:
        for _ in range(random.randint(3, 15)):
            ex_x = cx + random.randint(-int(radius*0.6), int(radius*0.6))
            ex_y = cy + random.randint(-int(radius*0.6), int(radius*0.6))
            cv2.circle(img, (ex_x, ex_y), random.randint(1, 4), (random.randint(40, 90), random.randint(200, 255), 255), -1)
            
    return img

def create_portrait_face_sample(w=224, h=224):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    bg_color = [random.randint(60, 160), random.randint(60, 160), random.randint(60, 160)]
    img[:] = bg_color
    
    skin_type = random.choice(['south_asian', 'caucasian', 'east_asian', 'deep_tan', 'african'])
    if skin_type == 'south_asian':
        skin_r = random.randint(145, 185)
        skin_g = random.randint(110, 145)
        skin_b = random.randint(80, 120)
    elif skin_type == 'caucasian':
        skin_r = random.randint(190, 235)
        skin_g = random.randint(160, 195)
        skin_b = random.randint(140, 180)
    elif skin_type == 'east_asian':
        skin_r = random.randint(180, 220)
        skin_g = random.randint(150, 185)
        skin_b = random.randint(120, 155)
    elif skin_type == 'deep_tan':
        skin_r = random.randint(130, 170)
        skin_g = random.randint(90, 130)
        skin_b = random.randint(60, 95)
    else:
        skin_r = random.randint(85, 130)
        skin_g = random.randint(60, 95)
        skin_b = random.randint(45, 75)
        
    skin_bgr = (skin_b, skin_g, skin_r)
    
    face_cx = w // 2 + random.randint(-15, 15)
    face_cy = h // 2 - random.randint(0, 25)
    face_rx = random.randint(50, 75)
    face_ry = int(face_rx * random.uniform(1.25, 1.45))
    cv2.ellipse(img, (face_cx, face_cy), (face_rx, face_ry), 0, 0, 360, skin_bgr, -1)
    
    hair_color = (random.randint(15, 45), random.randint(15, 45), random.randint(15, 45))
    cv2.ellipse(img, (face_cx, face_cy - int(face_ry * 0.7)), (int(face_rx * 1.15), int(face_ry * 0.6)), 0, 180, 360, hair_color, -1)
    
    eye_offset_x = int(face_rx * 0.45)
    eye_y = face_cy - int(face_ry * 0.15)
    cv2.line(img, (face_cx - eye_offset_x - 15, eye_y - 12), (face_cx - eye_offset_x + 15, eye_y - 10), hair_color, 3)
    cv2.line(img, (face_cx + eye_offset_x - 15, eye_y - 10), (face_cx + eye_offset_x + 15, eye_y - 12), hair_color, 3)
    for ex in [face_cx - eye_offset_x, face_cx + eye_offset_x]:
        cv2.ellipse(img, (ex, eye_y), (14, 8), 0, 0, 360, (235, 235, 240), -1)
        cv2.circle(img, (ex, eye_y), 5, (25, 25, 25), -1)
        
    if random.random() < 0.6:
        frame_color = random.choice([(20, 20, 20), (50, 50, 50), (180, 180, 190), (30, 40, 60)])
        cv2.rectangle(img, (face_cx - eye_offset_x - 22, eye_y - 14), (face_cx - eye_offset_x + 22, eye_y + 14), frame_color, 2)
        cv2.rectangle(img, (face_cx + eye_offset_x - 22, eye_y - 14), (face_cx + eye_offset_x + 22, eye_y + 14), frame_color, 2)
        cv2.line(img, (face_cx - eye_offset_x + 22, eye_y - 2), (face_cx + eye_offset_x - 22, eye_y - 2), frame_color, 2)
        cv2.line(img, (face_cx - eye_offset_x - 15, eye_y - 8), (face_cx - eye_offset_x + 5, eye_y + 10), (255, 255, 255), 1)
        
    cv2.line(img, (face_cx, eye_y + 8), (face_cx, eye_y + 28), (max(0, skin_b - 25), max(0, skin_g - 25), max(0, skin_r - 20)), 2)
    cv2.line(img, (face_cx - 15, eye_y + 45), (face_cx + 15, eye_y + 45), (max(0, skin_b - 20), max(0, skin_g - 35), max(0, skin_r + 15)), 3)
    
    neck_w = int(face_rx * 0.65)
    cv2.rectangle(img, (face_cx - neck_w, face_cy + int(face_ry * 0.6)), (face_cx + neck_w, h), skin_bgr, -1)
    
    shirt_color = random.choice([(240, 230, 200), (245, 245, 245), (210, 190, 160)])
    collar_pts = np.array([
        (face_cx - neck_w - 10, h), (face_cx - 20, face_cy + face_ry), (face_cx, face_cy + face_ry + 25),
        (face_cx + 20, face_cy + face_ry), (face_cx + neck_w + 10, h)
    ], np.int32)
    cv2.fillPoly(img, [collar_pts], shirt_color)
    
    suit_color = random.choice([(90, 90, 95), (120, 100, 80), (35, 35, 40), (70, 75, 80)])
    cv2.rectangle(img, (0, face_cy + face_ry + 10), (face_cx - neck_w + 5, h), suit_color, -1)
    cv2.rectangle(img, (face_cx + neck_w - 5, face_cy + face_ry + 10), (w, h), suit_color, -1)
    
    tie_color = random.choice([(30, 30, 35), (20, 20, 80), (70, 25, 25)])
    tie_pts = np.array([
        (face_cx - 10, face_cy + face_ry + 20), (face_cx + 10, face_cy + face_ry + 20),
        (face_cx + 14, h), (face_cx - 14, h)
    ], np.int32)
    cv2.fillPoly(img, [tie_pts], tie_color)
    
    return img

def create_noneye_sample(w=224, h=224):
    category = random.choice(['portrait', 'portrait', 'document', 'landscape', 'clothing', 'noise_geometry'])
    img = np.zeros((h, w, 3), dtype=np.uint8)
    
    if category == 'portrait':
        return create_portrait_face_sample(w, h)
    elif category == 'document':
        img[:] = random.randint(230, 255)
        for y in range(25, h - 25, random.randint(12, 18)):
            line_len = random.randint(w // 2, w - 30)
            cv2.line(img, (20, y), (line_len, y), (random.randint(10, 60), random.randint(10, 60), random.randint(10, 60)), random.randint(1, 2))
        if random.random() < 0.4:
            cv2.rectangle(img, (w // 3, h // 3), (2 * w // 3, 2 * h // 3), (50, 50, 50), 2)
    elif category == 'landscape':
        split = random.randint(h // 3, 2 * h // 3)
        img[:split] = [random.randint(180, 255), random.randint(140, 200), random.randint(50, 90)]
        img[split:] = [random.randint(30, 70), random.randint(110, 190), random.randint(40, 80)]
        cv2.circle(img, (random.randint(40, w - 40), random.randint(20, split - 20)), random.randint(15, 30), (80, 230, 255), -1)
    elif category == 'clothing':
        base = [random.randint(60, 140), random.randint(60, 140), random.randint(60, 140)]
        img[:] = base
        for x in range(0, w, random.randint(8, 20)):
            cv2.line(img, (x, 0), (x, h), (random.randint(30, 60), random.randint(30, 60), random.randint(30, 60)), 1)
        for y in range(0, h, random.randint(8, 20)):
            cv2.line(img, (0, y), (w, y), (random.randint(30, 60), random.randint(30, 60), random.randint(30, 60)), 1)
    else:
        img = np.random.randint(20, 230, (h, w, 3), dtype=np.uint8)
        for _ in range(random.randint(2, 6)):
            pt1 = (random.randint(0, w), random.randint(0, h))
            pt2 = (random.randint(0, w), random.randint(0, h))
            cv2.rectangle(img, pt1, pt2, (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)), -1)
            
    return img

class AdvancedRetinalDataset(Dataset):
    def __init__(self, num_samples=2400):
        self.samples = []
        print(f'Generating {num_samples} diverse training samples (Fundus vs Portraits/Non-Eyes)...')
        
        real_fundus_imgs = []
        for path in ['sample_real_fundus.png', 'user_retina_isolated.png',
                     r'C:/Users/DELL/.gemini/antigravity/brain/83a8594b-73c9-401b-8ba6-024177eb2f1c/.user_uploaded/media_1788888654346.png']:
            if os.path.exists(path):
                im = cv2.imread(path)
                if im is not None:
                    real_fundus_imgs.append(im)
                    
        real_portrait_imgs = []
        portrait_path = r'C:/Users/DELL/.gemini/antigravity/brain/83a8594b-73c9-401b-8ba6-024177eb2f1c/.user_uploaded/media_1788897068996.jpg'
        if os.path.exists(portrait_path):
            p_img = cv2.imread(portrait_path)
            if p_img is not None:
                real_portrait_imgs.append(p_img)
                h_p, w_p = p_img.shape[:2]
                real_portrait_imgs.append(p_img[50:400, 100:450])
                real_portrait_imgs.append(p_img[350:800, 50:600])
                real_portrait_imgs.append(p_img[0:300, 0:300])
                
        if real_fundus_imgs:
            for _ in range(300):
                base = random.choice(real_fundus_imgs)
                h_b, w_b = base.shape[:2]
                M = cv2.getRotationMatrix2D((w_b // 2, h_b // 2), random.uniform(-180, 180), random.uniform(0.85, 1.15))
                aug = cv2.warpAffine(base, M, (w_b, h_b), borderMode=cv2.BORDER_REFLECT)
                if random.random() < 0.5: aug = cv2.flip(aug, 1)
                aug = cv2.resize(aug, (224, 224))
                aug = np.clip(aug.astype(np.float32) * random.uniform(0.85, 1.15) + random.randint(-15, 15), 0, 255).astype(np.uint8)
                self.samples.append((aug, 1))
                
        for _ in range(900):
            self.samples.append((create_fundus_sample(224, 224), 1))
            
        if real_portrait_imgs:
            for _ in range(400):
                base = random.choice(real_portrait_imgs)
                h_b, w_b = base.shape[:2]
                if h_b > 30 and w_b > 30:
                    M = cv2.getRotationMatrix2D((w_b // 2, h_b // 2), random.uniform(-25, 25), random.uniform(0.85, 1.15))
                    aug = cv2.warpAffine(base, M, (w_b, h_b), borderMode=cv2.BORDER_REFLECT)
                    if random.random() < 0.5: aug = cv2.flip(aug, 1)
                    aug = cv2.resize(aug, (224, 224))
                    aug = np.clip(aug.astype(np.float32) * random.uniform(0.85, 1.15) + random.randint(-15, 15), 0, 255).astype(np.uint8)
                    self.samples.append((aug, 0))
                    
        for _ in range(800):
            self.samples.append((create_noneye_sample(224, 224), 0))
            
        random.shuffle(self.samples)
        print(f'Total compiled samples: {len(self.samples)} (Fundus: {sum(1 for s in self.samples if s[1]==1)}, Non-Eye: {sum(1 for s in self.samples if s[1]==0)})')
        
    def __len__(self):
        return len(self.samples)
        
    def __getitem__(self, idx):
        img_bgr, label = self.samples[idx]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        tensor = torch.from_numpy(img_rgb).permute(2, 0, 1).float() / 255.0
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        tensor = (tensor - mean) / std
        return tensor, torch.tensor(label, dtype=torch.long)

def train_model(epochs=8, batch_size=32, lr=1e-3, save_path='retina_eye_classifier.pth'):
    print('Initializing RetinaEyeResNet Classifier Training...')
    dataset = AdvancedRetinalDataset(num_samples=2400)
    train_size = int(0.85 * len(dataset))
    val_size = len(dataset) - train_size
    train_set, val_set = torch.utils.data.random_split(dataset, [train_size, val_size])
    
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)
    
    model = RetinaEyeClassifier()
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    
    best_val_acc = 0.0
    
    for epoch in range(1, epochs + 1):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        
        for images, labels in train_loader:
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            
            running_loss += loss.item() * images.size(0)
            _, preds = torch.max(outputs, 1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)
            
        scheduler.step()
        train_loss = running_loss / total
        train_acc = (correct / total) * 100.0
        
        model.eval()
        val_correct = 0
        val_total = 0
        val_loss = 0.0
        with torch.no_grad():
            for val_imgs, val_labels in val_loader:
                val_out = model(val_imgs)
                v_loss = criterion(val_out, val_labels)
                val_loss += v_loss.item() * val_imgs.size(0)
                _, val_preds = torch.max(val_out, 1)
                val_correct += (val_preds == val_labels).sum().item()
                val_total += val_labels.size(0)
                
        val_acc = (val_correct / val_total) * 100.0
        avg_val_loss = val_loss / val_total
        print(f'Epoch [{epoch}/{epochs}] - Train Loss: {train_loss:.4f} | Train Acc: {train_acc:.1f}% | Val Loss: {avg_val_loss:.4f} | Val Acc: {val_acc:.1f}%')
        
        if val_acc >= best_val_acc:
            best_val_acc = val_acc
            torch.save(model.state_dict(), save_path)
            
    print(f'Training Complete! Best Validation Accuracy: {best_val_acc:.1f}%')
    print(f'Saved optimized model weights to {save_path}')
    return model

if __name__ == '__main__':
    train_model(epochs=8, batch_size=32, lr=1e-3, save_path='retina_eye_classifier.pth')
