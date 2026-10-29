import os
import time

import pandas as pd
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


base_url = f'https://www.data.go.kr/tcs/dss/selectDataSetList.do?sType=total&dType=FILE&keyword=%EA%B5%AD%ED%86%A0%EA%B5%90%ED%86%B5%EB%B6%80&beforeKeyword=%EA%B5%AD%ED%86%A0%EA%B5%90%ED%86%B5%EB%B6%80&detailKeyword=&publicDataPk=&recmSe=&detailText=&relatedKeyword=&commaNotInData=&commaAndData=&commaOrData=&must_not=&tabId=&dataSetCoreTf=&coreDataNm=&sort=score&relRadio=&orgFullName=&orgFilter=&orgNm=&orgSearch=&currentPage=1&perPage=10&brm=&instt=&svcType=&kwrdArray=&extsn=&coreDataNmArray=&pblonsipScopeCode='

page_data_name_list = []  # 데이터명
page_data_inst_list = [] #기관명

driver = webdriver.Chrome()
wait = WebDriverWait(driver, 10)

end_page = 148

driver.maximize_window()

for target_page in range(1, end_page + 1):
    target_url = base_url.replace(
        "&currentPage=1&",
        f"&currentPage={target_page}&",
    )

    driver.get(target_url)
    time.sleep(2)

    table_selector = "#contents > div.data-list-wrap > div:nth-child(9) > div.data-list-group > div > div.apply-result"

    div_list = driver.find_elements(
        By.CSS_SELECTOR,
        f"{table_selector} > div"
    )

    print("하위 div 개수:", len(div_list))

    for i in range(1, len(div_list) + 1) :
        item_name_selector = f"#contents > div.data-list-wrap > div:nth-child(9) > div.data-list-group > div > div.apply-result > div:nth-child({i}) > div.in-result-item > div.apply-result-link > a"
        item_name = driver.find_element(
            By.CSS_SELECTOR,
            item_name_selector
        )
        page_data_name_list.append(item_name.text)

        inst_name_selector = f"#contents > div.data-list-wrap > div:nth-child(9) > div.data-list-group > div > div.apply-result > div:nth-child({i}) > div.in-result-item > ul > li:nth-child(1)"
        inst_name = driver.find_element(
            By.CSS_SELECTOR,
            inst_name_selector
        )
        page_data_inst_list.append(inst_name.text)

data_name_df = pd.DataFrame(
    {
        "데이터명": page_data_name_list,
        "제공기관명" : page_data_inst_list
    }
    )

data_name_df.to_excel(r'국토교통부_공공데이터_261001.xlsx', index=False)