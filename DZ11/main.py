from legal_api import LegalAPI

TOKEN = "4123saedfasedfsadf4324234f223ddf23"
api = LegalAPI(token=TOKEN, base_url="https://legal-api.sirotinsky.com")

# 1) Посмотреть, что есть в схеме:
print(api.list_endpoints()[:20])

# 2) Вызвать метод по operationId (из схемы):
# data = api.call("searchEFRSBNotices", query={"inn": "7707083893"})

# 3) Удобные ЕФРСБ-методы:
# notices = api.efrsb_list_notices(query={"inn": "7707083893", "limit": 50})
# debtor  = api.efrsb_get_debtor(query={"inn": "7707083893"})
# case    = api.efrsb_get_case(query={"caseNumber": "А40-12345/2024"})
