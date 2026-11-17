"""수집 대상별 기본 검색 URL을 정의한다. 다른 검색 조건은 --url로 지정한다."""

from .common import set_query

DEFAULT_URLS = {'file': 'https://www.data.go.kr/tcs/dss/selectDataSetList.do?sType=total&dType=FILE&keyword=%EA%B5%AD%ED%86%A0%EA%B5%90%ED%86%B5%EB%B6%80&beforeKeyword=%EA%B5%AD%ED%86%A0%EA%B5%90%ED%86%B5%EB%B6%80&detailKeyword=&publicDataPk=&recmSe=&detailText=&relatedKeyword=&commaNotInData=&commaAndData=&commaOrData=&must_not=&tabId=&dataSetCoreTf=&coreDataNm=&sort=score&relRadio=&orgFullName=&orgFilter=&orgNm=&orgSearch=&currentPage=1&perPage=10&brm=&instt=&svcType=&kwrdArray=&extsn=&coreDataNmArray=&pblonsipScopeCode=',
 'api': 'https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=API&keyword=&operator=AND&detailKeyword=&publicDataPk=&recmSe=&detailText=&relatedKeyword=&commaNotInData=&commaAndData=&commaOrData=&must_not=&tabId=&dataSetCoreTf=&coreDataNm=&sort=inqireCo&relRadio=&orgFullName=%EA%B5%AD%ED%86%A0%EA%B5%90%ED%86%B5%EB%B6%80&orgFilter=%EA%B5%AD%ED%86%A0%EA%B5%90%ED%86%B5%EB%B6%80&org=%EA%B5%AD%ED%86%A0%EA%B5%90%ED%86%B5%EB%B6%80&orgSearch=&currentPage=1&perPage=40&brm=&instt=&svcType=&kwrdArray=&extsn=&coreDataNmArray=&pblonsipScopeCode=PBDE07',
 'usecase': 'https://www.data.go.kr/tcs/puc/selectPublicUseCaseListView.do?pageIndex=1&prcuseCaseSn=1059600&hbrdSe=&searchCondition1=&searchCondition2=instt&cndCtgryEdu=Y&cndCtgryMngtTrt=Y&cndCtgryPblAdmin=Y&cndCtgryFnc=Y&cndCtgryEmplIndst=Y&cndCtgrySocWlf=Y&cndCtgryFdHlth=Y&cndCtgryCulTour=Y&cndCtgryHlthCare=Y&cndCtgryDisSfty=Y&cndCtgryTrnsLgc=Y&cndCtgryEnvWthr=Y&cndCtgrySncTech=Y&cndCtgryAgriFish=Y&cndCtgryUnfc=Y&cndCtgryLaw=Y&bindCndCtgry=OC0001%2COC0002%2COC0003%2COC0004%2COC0005%2COC0006%2COC0007%2COC0008%2COC0009%2COC0010%2COC0011%2COC0012%2COC0013%2COC0014%2COC0015%2COC0016&sort-post=instt&searchKeyword1=%EA%B5%AD%ED%86%A0%EA%B5%90%ED%86%B5%EB%B6%80&prcuseType='}

# 기관 필터는 orgNm으로 전달한다. org/orgFilter만으로는 기관 조건이 적용되지 않는다.
DEFAULT_URLS['api'] = set_query(DEFAULT_URLS['api'], orgNm='국토교통부')

