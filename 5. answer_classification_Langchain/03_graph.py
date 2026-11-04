import seaborn as sns
import matplotlib.font_manager as fm
import pandas as pd
import matplotlib.pyplot as plt

font_path = "C:/Windows/Fonts/H2HDRM.ttf"
font_name = fm.FontProperties(fname=font_path).get_name()
plt.rc('font', family=font_name)

df = pd.read_excel(r'Q19_분류결과_NEW.xlsx')
df.head(1)
df = df[['category']]
df.head(1)

exploded = df['category'].str.split(',').explode().str.strip()
exploded

# 2. 각 카테고리별 개수 계산
counts = exploded.value_counts()
df_counts = counts.reset_index()
df_counts.columns = ['category', '개수']
df_counts['퍼센트'] = (df_counts['개수'] / df_counts['개수'].sum() * 100).round(1)
df_counts.to_excel('Q19_퍼센티지.xlsx', index=False)

# 3. 파이 차트 그리기
plt.figure(figsize=(6, 6))
counts.plot.pie(
    autopct='%1.1f%%', 
    startangle=90, 
    counterclock=False, 
    textprops={'fontsize': 12}
)
plt.ylabel("")  # y축 레이블 제거
plt.tight_layout()
plt.show()
