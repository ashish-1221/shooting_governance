## Total Structure of the both PDFs

# 2018 Asian Games

## Pages Types based on title

1. Cover Page
2. Competition Officials
3. Competition Schedule
4. Entry List by NOC <- Required
   - Required for DOB for each player
   - Structure
     - Columns present are NOC, Name, Bib No. ,Gender, DOB, DS, Event
     - NOC is declared in the first row, followed by Candidate Names for each event.
5. Number of Entries by NOC
6. Medallists by Event
7. Medal Standings
8. Records
9. Records Broken / Equalled
10. Results <- Required to be parsed
    - Event Type and Round Type is present in the first header of each page on the right handk
    - Structure based on events
      - 10m Air Rifle Men - Final, Qualification
      - 10m Air Pistol Men - Final, Qualification
      - 25m Rapid Fire Pistol Men - Final, Qualification
      - Trap Men - Final, Qualification
      - Skeet Men - Final,Qualification
      - Double Trap Men - Final, Qualification
      - 50m Rifle 3 Positions Men - Final,Qualification
      - 300m Standard Rifle Men - Competition
      - 10m Running Target Men - Qualification
      - 10m Running Target Mixed Men - Competition
      - 10m Air Rifle Women - Final, Qualification
      - 50m Rifle 3 Positions Women - Final, Qualification
      - 10m Air Pistol Women - Final, Qualification
      - 25m Pistion Women - Final, Qualification
      - Trap Women - Final, Qualification
      - Skeet Women - Final, Qualification
      - Double Trap Women - Competition
        - Rank, Bib No.,Name, NOC Code, Total
        - Extract only rows which contain the rank values
      - 10m Running Target Men - Medal Matches
        - Rank, Bib No.,Name, NOC Code, Total
        - Round Types are defined in the first header then the results in the above form
          - Round Types are Gold Medal Match, Bronze Medal Match, Semifinal 1, Semifinal 2
      - 10m Air Rifle Mixed Team - Final, Qualification
      - 10m Air Pistol Mixed Team - Final, Qualification
      - Trap Mixed Team - Final, Qualification
        - Rank, Bib No.,Name, NOC Code, Total
        - The player names are present below the rank row,
        - The name cell with the rank filled, Name contains the country name
        - Need to extract the below all rows for names of the candidates before another row with the rank cell filled
        - Need to extract the team total from the row containing the rank column filled, and below the individual competitor names with total scored by the individual player
        - Total Value for a team may be present in the first row of the row group containing the team, else the first row
        - Example the total cell value with the rank cell filled is 836.7, and below the individual player scores are 418 and 417, then extraction for the player in the form of 836.7 (418) for player a and 836.7(417) for player b, and if player totals are not present then only 836.7 for each player a and b.

# 2022 Asian Games

- Pages 29- 40 <- Required to be parsed
  - Contain player information in the form of rank, rating, name, birth and Nation
- Results <- Required to be parsed
  - Event Type and Round Type is present in the first header of each page
  - Structure based on the event names
    - 10m Air Rifle Men - Final, Qualification
    - 10m Air Pistol Men - Final, Qualification
    - 50m Rifle 3 Positions Men - Final
    - 25m Rapid Fire Pistol Men - Final
    - Trap Men - Final, Qualification Stage 2
    - Skeet Men - Final, Qualifications Stage 2
    - 10m Air Rifle Women - Qualification
    - 10m Air Rifle Women - Final
    - 50m Rifle 3 Positions Women - Final
    - 10m Air Pistol Women - Final, Qualification
    - 25m Pistol Women - Final
    - 25m Pistol Women - Final, Qualifications Rapid
    - Trap Women - Final, Qualifications Stage 2
    - Skeet Women - Final, Qualifications Stage 2
    - 10m Running Target Women - Final
    - 10m Air Rifle Mixed Team - Finals Bronze Medal Match 1, Finals Bronze Medal Match 2, Finals Gold Medal Match
      - Rank, Bib No.,Name, NOC Code, Total
      - Extract only rows which contain the rank values, as total value is present in that value
      - Total value may be present in the first cell of the total column of the row group or the last cell of the total column.
    - 10m Air Rifle Team Men - Final
    - 50m Rifle 3 Positions Team Men - Final
    - 10m Air Pistol Team Men - Final
    - Trap Team Men - Final,
    - Skeet Team Men - Final
    - 10m Running Target Team Men - Final
    - 10m Running Target Mixed Run Men - Final
    - 10m Air Rifle Team Women - Final
    - 50m Rifle 3 Positions Team Women - Final
    - 10m Air Pistol Team Women - Final
    - 25m Pistol Team Women - Final
    - Trap Team Women - Final
    - Skeet Team Women - Final
    - 10m Running Target Team Women - Final
    - 10m Air Rifle Mixed Team - Qualification, Finals Bronze Medal Match 1 ,Finals Bronze Medal Match 2, Finals Gold Medal Match
    - 10m Air Pistol Mixed Team - Qualification
    - Skeet Mixed Team - Finals Bronze Medal Match 1, Finals Bronze Medal Match 2, Finals Gold Medal Match, Qualification
      - Rank, Bib No.,Name, Total
      - The player names are present below the rank row,
      - The name cell with the rank filled, Name contains the country name
      - Need to extract the below all rows for names of the candidates before another row with the rank cell filled
      - Need to extract the team total from the row containing the rank column filled, and below the individual competitor names with total scored by the individual player
      - Example the total cell value with the rank cell filled is 836.7, and below the individual player scores are 418 and 417, then extraction for the player in the form of 836.7 (418) for player a and 836.7(417) for player b, and if player totals are not present then only 836.7 for each player a and b.
      - Total Value for a team may be present in the first row of the row group containing the team, else the first row

    - 50m Rifle 3 Positions Men - Qualification
    - 10m Running Target Men - Final
    - 50m Rifle 3 Positions Women - Qualification
      - The total is present in the last row of the row group containing the rank

# Output Schema

    - Championship Name
    - Event Name
    - Round Type
    - Rank
    - Bib No.
    - Name
    - NOC
    - Totals
