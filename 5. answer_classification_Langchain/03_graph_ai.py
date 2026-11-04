import seaborn as sns
import matplotlib.font_manager as fm
import pandas as pd
import matplotlib.pyplot as plt

font_path = "C:/Windows/Fonts/H2HDRM.ttf"
font_name = fm.FontProperties(fname=font_path).get_name()
plt.rc('font', family=font_name)

df = pd.read_excel(r'Q20_AI문항_분류결과_new.xlsx')
df.head(1)
df = df[['category']]
df.head(1)

# 2. '기타' 카테고리 제외
df_filtered = df[df['category'] != '기타']

# 3. 각 카테고리별 개수 계산
counts = df_filtered['category'].value_counts()
df_counts = counts.reset_index()
df_counts.columns = ['카테고리', '개수']

# 4. seaborn을 사용한 막대그래프 그리기
plt.figure(figsize=(6, 6))
sns.barplot(data=df_counts, x='카테고리', y='개수')
plt.title('AI 학습데이터 수요(기타 제외)')
plt.xlabel('')
plt.ylabel('')
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

# 각 카테고리별 개수와 퍼센트 계산
category_counts = df['category'].value_counts().reset_index()
category_counts.columns = ['category', 'count']
category_counts['percent'] = category_counts['count'] / category_counts['count'].sum() * 100
category_counts

category_counts.to_excel("Q20_퍼센티지.xlsx", index=False)

