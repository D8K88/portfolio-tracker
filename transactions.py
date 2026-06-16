# Transaction history for 윤선화 and 김희돈
# type: "buy" | "sell" | "split"
# split: 액면분할 이벤트 (old_shares -> new_shares 비율로 기존 lot 조정)

STOCK_INFO = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "005490": "POSCO홀딩스",
    "009900": "명신산업",
    "365340": "성일하이텍",
    "196170": "알테오젠",
    "257720": "실리콘투",
    "000270": "기아",
    "097520": "엠씨넥스",
    "025900": "동화기업",
    "063170": "서울옥션",
    "064350": "현대로템",
    "102710": "이엔에프테크놀로지",
    "023160": "태광",
    "007660": "이수페타시스",
    "034020": "두산에너빌리티",
    "042660": "한화오션",
    "103590": "일진전기",
}

TRANSACTIONS = [
    # ════════════════════════════════════════
    #  윤선화
    # ════════════════════════════════════════

    # 삼성전자
    {"date":"2020-09-21","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":59700,"shares":30},
    {"date":"2020-10-17","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":60000,"shares":15},
    {"date":"2020-11-09","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":60600,"shares":8},
    {"date":"2020-11-11","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":61000,"shares":10},
    {"date":"2020-11-26","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":67300,"shares":15},
    {"date":"2020-11-26","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":67200,"shares":22},
    {"date":"2021-01-04","owner":"윤선화","code":"005930","name":"삼성전자","type":"sell","price":80600,"shares":13},
    {"date":"2021-01-04","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":81100,"shares":13},
    {"date":"2021-01-04","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":81300,"shares":13},
    {"date":"2021-01-19","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":87800,"shares":6},
    {"date":"2021-05-24","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":79800,"shares":16},
    {"date":"2022-03-10","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":70600,"shares":15},
    {"date":"2022-06-21","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":58900,"shares":17},
    {"date":"2026-05-15","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":290000,"shares":10},
    {"date":"2026-05-20","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":290000,"shares":1,"note":"추정 매입 (메모 누락)"},
    {"date":"2026-05-26","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":298500,"shares":5},
    {"date":"2026-05-26","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":299500,"shares":2},
    {"date":"2026-05-27","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":314500,"shares":3},
    {"date":"2026-06-09","owner":"윤선화","code":"005930","name":"삼성전자","type":"buy","price":306500,"shares":9},

    # 엠씨넥스
    {"date":"2021-01-11","owner":"윤선화","code":"097520","name":"엠씨넥스","type":"buy","price":48750,"shares":10},
    {"date":"2021-07-14","owner":"윤선화","code":"097520","name":"엠씨넥스","type":"sell","price":46800,"shares":10},
    {"date":"2022-05-24","owner":"윤선화","code":"097520","name":"엠씨넥스","type":"buy","price":39850,"shares":60},
    {"date":"2026-05-26","owner":"윤선화","code":"097520","name":"엠씨넥스","type":"sell","price":23500,"shares":60},

    # 서울옥션
    {"date":"2021-04-20","owner":"윤선화","code":"063170","name":"서울옥션","type":"buy","price":14900,"shares":60},
    {"date":"2021-04-20","owner":"윤선화","code":"063170","name":"서울옥션","type":"buy","price":15300,"shares":20},
    {"date":"2021-05-04","owner":"윤선화","code":"063170","name":"서울옥션","type":"sell","price":15800,"shares":80},

    # 동화기업 (액면분할: 13주 → 32주)
    {"date":"2021-07-06","owner":"윤선화","code":"025900","name":"동화기업","type":"buy","price":74000,"shares":8},
    {"date":"2021-07-14","owner":"윤선화","code":"025900","name":"동화기업","type":"buy","price":84000,"shares":5},
    # 액면분할 이벤트 (정확한 분할일 미확인, 2022년 초 추정)
    {"date":"2022-01-01","owner":"윤선화","code":"025900","name":"동화기업","type":"split","old_shares":13,"new_shares":32,"note":"액면분할 (정확한 일자 미확인)"},
    {"date":"2026-05-27","owner":"윤선화","code":"025900","name":"동화기업","type":"sell","price":9810,"shares":32},

    # 현대로템
    {"date":"2022-02-08","owner":"윤선화","code":"064350","name":"현대로템","type":"buy","price":19300,"shares":60},
    {"date":"2022-03-10","owner":"윤선화","code":"064350","name":"현대로템","type":"sell","price":18950,"shares":60},

    # 이엔에프테크놀로지
    {"date":"2022-05-26","owner":"윤선화","code":"102710","name":"이엔에프테크놀로지","type":"buy","price":34950,"shares":30},
    {"date":"2025-11-02","owner":"윤선화","code":"102710","name":"이엔에프테크놀로지","type":"sell","price":46700,"shares":30},

    # 태광
    {"date":"2022-11-17","owner":"윤선화","code":"023160","name":"태광","type":"buy","price":18000,"shares":1115},
    {"date":"2023-07-06","owner":"윤선화","code":"023160","name":"태광","type":"sell","price":19800,"shares":550},
    {"date":"2023-07-06","owner":"윤선화","code":"023160","name":"태광","type":"sell","price":20000,"shares":565},
    {"date":"2024-06-20","owner":"윤선화","code":"023160","name":"태광","type":"buy","price":12650,"shares":85},
    {"date":"2026-01-26","owner":"윤선화","code":"023160","name":"태광","type":"sell","price":25300,"shares":85},

    # POSCO홀딩스
    {"date":"2023-05-31","owner":"윤선화","code":"005490","name":"POSCO홀딩스","type":"buy","price":367000,"shares":28},
    {"date":"2023-07-18","owner":"윤선화","code":"005490","name":"POSCO홀딩스","type":"sell","price":485000,"shares":28},
    {"date":"2023-07-25","owner":"윤선화","code":"005490","name":"POSCO홀딩스","type":"buy","price":668000,"shares":12},
    {"date":"2026-06-16","owner":"윤선화","code":"005490","name":"POSCO홀딩스","type":"sell","price":391000,"shares":12},

    # 기아
    {"date":"2023-07-10","owner":"윤선화","code":"000270","name":"기아","type":"buy","price":88200,"shares":250},
    {"date":"2024-02-02","owner":"윤선화","code":"000270","name":"기아","type":"sell","price":118800,"shares":100},
    {"date":"2024-05-24","owner":"윤선화","code":"000270","name":"기아","type":"sell","price":120400,"shares":150},

    # 명신산업
    {"date":"2023-07-20","owner":"윤선화","code":"009900","name":"명신산업","type":"buy","price":21700,"shares":300},
    {"date":"2026-06-04","owner":"윤선화","code":"009900","name":"명신산업","type":"sell","price":8950,"shares":300},

    # 성일하이텍
    {"date":"2023-07-20","owner":"윤선화","code":"365340","name":"성일하이텍","type":"buy","price":149600,"shares":48},
    {"date":"2026-06-10","owner":"윤선화","code":"365340","name":"성일하이텍","type":"sell","price":51600,"shares":48},

    # 알테오젠
    {"date":"2024-04-04","owner":"윤선화","code":"196170","name":"알테오젠","type":"buy","price":171900,"shares":23},
    {"date":"2024-06-04","owner":"윤선화","code":"196170","name":"알테오젠","type":"sell","price":232000,"shares":23},
    {"date":"2025-07-31","owner":"윤선화","code":"196170","name":"알테오젠","type":"buy","price":452500,"shares":7},
    {"date":"2025-11-02","owner":"윤선화","code":"196170","name":"알테오젠","type":"sell","price":519000,"shares":7},
    {"date":"2025-12-05","owner":"윤선화","code":"196170","name":"알테오젠","type":"buy","price":465000,"shares":20},
    {"date":"2026-06-16","owner":"윤선화","code":"196170","name":"알테오젠","type":"sell","price":347500,"shares":20},

    # 일진전기
    {"date":"2024-04-23","owner":"윤선화","code":"103590","name":"일진전기","type":"buy","price":19120,"shares":48},
    {"date":"2024-10-18","owner":"윤선화","code":"103590","name":"일진전기","type":"sell","price":25500,"shares":48},

    # 이수페타시스
    {"date":"2024-06-10","owner":"윤선화","code":"007660","name":"이수페타시스","type":"buy","price":48850,"shares":200},
    {"date":"2025-08-01","owner":"윤선화","code":"007660","name":"이수페타시스","type":"sell","price":63200,"shares":200},

    # 실리콘투
    {"date":"2024-06-13","owner":"윤선화","code":"257720","name":"실리콘투","type":"buy","price":50400,"shares":250},
    {"date":"2026-06-16","owner":"윤선화","code":"257720","name":"실리콘투","type":"sell","price":35419,"shares":250},

    # 두산에너빌리티
    {"date":"2024-07-18","owner":"윤선화","code":"034020","name":"두산에너빌리티","type":"buy","price":24900,"shares":122},
    {"date":"2025-08-01","owner":"윤선화","code":"034020","name":"두산에너빌리티","type":"sell","price":61600,"shares":122},

    # 한화오션
    {"date":"2024-11-13","owner":"윤선화","code":"042660","name":"한화오션","type":"buy","price":36550,"shares":34},
    {"date":"2025-09-04","owner":"윤선화","code":"042660","name":"한화오션","type":"sell","price":113300,"shares":34},

    # SK하이닉스
    {"date":"2026-05-15","owner":"윤선화","code":"000660","name":"SK하이닉스","type":"buy","price":1845000,"shares":11},

    # ════════════════════════════════════════
    #  김희돈
    # ════════════════════════════════════════

    # 삼성전자
    {"date":"2025-09-23","owner":"김희돈","code":"005930","name":"삼성전자","type":"buy","price":84800,"shares":100},
    {"date":"2025-11-05","owner":"김희돈","code":"005930","name":"삼성전자","type":"buy","price":100300,"shares":100},

    # SK하이닉스
    {"date":"2026-05-12","owner":"김희돈","code":"000660","name":"SK하이닉스","type":"buy","price":1845000,"shares":10},
    {"date":"2026-05-15","owner":"김희돈","code":"000660","name":"SK하이닉스","type":"buy","price":1860000,"shares":1},
]

# 현재 보유 포지션 (브로커리지 기준 평균단가 - 분할 등 반영)
CURRENT_POSITIONS = {
    "윤선화": [
        {"code":"005930","name":"삼성전자","shares":197,"avg_price":103420},
        {"code":"000660","name":"SK하이닉스","shares":11,"avg_price":1845000},
    ],
    "김희돈": [
        {"code":"005930","name":"삼성전자","shares":200,"avg_price":92550},
        {"code":"000660","name":"SK하이닉스","shares":11,"avg_price":1846364},
    ],
}
