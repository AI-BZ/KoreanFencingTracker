제26회 전국남녀대학펜싱선수권대회 여대 플러레(개)  기준으로 테이블로 만들어진 엘리미나시옹디렉트를
  분석해보자
  대진표 - 종별 여대 플러래(개) - 엘리나시옹디렉트 - 32강전 탭 (~8강전 까지 이용 후 8강탭에서
  준결승~결승~우승자 <= 준결승 부터가  본선) * 128강 이상 라운드가 있는 대회는 탭도 여러개 존재
  여기 밑으로 테이블로 만들어진 트리형상의 경기결과들이 나오고 있어,
  1. 최초 라운드 설정을 잘해야 되 이거는 #gameForm > div.game-wrap > div > div > table > tbody >
  tr:nth-child(3) > td > div.team-wrap.tab-tableau-wrap   여기에서 첫번째 #gameForm > div.game-wrap > div >
  div > table > tbody > tr:nth-child(3) > td > div.team-wrap.tab-tableau-wrap > div > ul > li.on  으로
  확인을해야 해 여기에서는 = "32강전" 그리고 그 다음에나오는 탭정보에 "8강전"이 나오면 32강전 탭에서는
  32강~16강까지 데이터를 스크래핑으로 잡으면 되,
  2. 32강이 첫 라운드인걸 우리는 찾았고, #A_table > tbody > tr > td.row_table.row01  여기에 32강전, #A_table
  > tbody > tr > td.row_table.row02 여기에 16강전을 찾으면되고, 8강전은 "8강전" 탭으로 이동해서 스크래핑
  3. #A_table > tbody > tr > td.row_table.row01 첫번째 라운드인 32강 열이고  여기에는 tr class="user_box"가
  32개가 있어, 1시합 첫번째 "user_box" : 두번째 "user_box" / 2시합 세번째  "user_box" : 네번쨰"user_box" ...
  / 16시합 31번째 "user_box" : 32번째 "user_box"  이렇게 16개 시합이 만들어져있어,
  4. 다만 첫번째 라운드 시합에는 한선수의 "user_box"는 정보가 있고 한선수의 "user_box"에 정보가 비어있는
  시합들이 있어, 이거는 "user_box"에 정보가 있는 선수가 자동으로 다음라운드를 진출하는것이고, 시합데이터로는
  쓰지않고, 승 패도 가려지지 않고, 정보가 있는 선수가 다음라운드인 16강에 진출했다는 것만 인식하면되,
  5. 이렇게 해서 총 16경기 중 실제 시합이있는 선수의 승자와, 32강에서 상대선수가 비어있어서 자동으로 16강에
  올라 간 선수는 #A_table > tbody > tr > td.row_table.row02 에 올라가게 되고 이들이 두번째 라운드인 16강
  진출자들이야.
  (#A_table > tbody > tr > td.row_table.row01 > table > tbody > tr:nth-child(6) > td 여기에 pool 전체 순위와
  이름 소속이 적혀있어)
  6. 32강 1시합 시합 승자 또는 자동 승자는 첫번째 #A_table > tbody > tr > td.row_table.row02 > table > tbody
  > tr:nth-child(2)  "user_box"에 2시합은 두번째 "user_box"..... 16시합은 16번째 "user_box"
  7. 여기서 32강 자동 승 16강 진출자는 호세진 처럼 #A_table > tbody > tr > td.row_table.row02 > table >
  tbody > tr:nth-child(2) > td > div.info > p.user_aff  여기에 공란으로 비어있고,
  8. 32강 시합을 하고 승리해서 16강 진출한 박수빈 처럼 #A_table > tbody > tr > td.row_table.row02 > table >
  tbody > tr:nth-child(4) > td > div.info > p.user_aff  여기에 32강 시합에서의 점수가 기록되게 되.
  (#A_table > tbody > tr > td.row_table.row02 > table > tbody > tr:nth-child(4) > td > div.num   박수빈 순위
  정보가 16으로 변경된 이유는 32강에서 자기보다 pool 순위가 높은 선수를 이기고 올라오면 이긴선수의 pool
  순위를 자기가 가져오게 되)
  9. 두번째 라운드인 16강 #A_table > tbody > tr > td.row_table.row02 에는 총 8게임이 있고, 1시합 첫번째
  "user_box" : 두번째 "user_box" / 2시합 세번째  "user_box" : 네번쨰"user_box" ...
    / 8시합 15번째 "user_box" : 16번째 "user_box"  이렇게 8개 시합이 만들어져있어,
  10. 세번째 라운드인 8강 #A_table > tbody > tr > td.row_table.row03 총 4게임이 있고, 1시합 첫번째
    "user_box" : 두번째 "user_box" / 2시합 세번째  "user_box" : 네번쨰"user_box" ...
      / 4시합 7번째 "user_box" : 8번째 "user_box"  이렇게 4개 시합이 만들어져있어,
  8강에서의 시합결과는 앞에서와 같이 #A_table > tbody > tr > td.row_table.row03 의 "user_box"에 기록이
  되있어.
  11. 네번째 라운드인 4강 준결승은 #gameForm > div.game-wrap > div > div > table > tbody > tr:nth-child(3) >
  td > div.team-wrap.tab-tableau-wrap > div > ul > li.on > a  여기로 이동해서 확인, 탭이름은 8강이지만 그
  다음 라운드인 4강부터 이 탭 태이블을 이용해야 해 이유는 16강 결과 표시가 없어.
  12. 앞에서와 같이 4강 준결승 #A_table > tbody > tr > td.row_table.row02, 다음 결승 데이터 #A_table > tbody
  > tr > td.row_table.row03를 가져오고, 최종 우승자가 마지막 #A_table > tbody > tr > td.row_table.row04
  에표시되고 "user_box"에 결승 점수가 기록되있어, 여기서 최종 우승자와 경기결과 1등이 동일 선수인지 반드시
  검증해야되