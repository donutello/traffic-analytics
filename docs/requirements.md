# Requirements

## The customer's task

Customer: JSC "Minimaks-94". Project: "Statistical and incident analysis of traffic volume based on data from road radar sensors". Time frame: one semester.

The customer's information system holds a large archive of traffic volume statistics. Its users (dispatchers and the contractors who maintain federal roads) need to see changes in traffic metrics almost in real time, but today reports and analytics are only available for the previous day.

The team's goal: suggest ways to detect abnormal values in the traffic flow and its vehicle mix, define the metrics that reveal such deviations, and try to forecast traffic volume. The customer already has an analysis module based on simple AI-generated metrics (the "corporate system"), but those metrics do not work well enough.

Recommended reading: ODM 218.2.020-2012 "Guidelines for estimating the capacity of roads" (ОДМ 218.2.020-2012 «Методические рекомендации по оценке пропускной способности автомобильных дорог»).

## Functional requirements for the dashboard

- **FR1.** Interactive time series view with a smooth switch from weekly to daily to hourly detail. The user selects a period on the overview chart, and the view zooms in on it automatically.
- **FR2.** All visualizations clearly separate three states of the data: normal behaviour, detected anomalies and filled-in gaps. The user must instantly tell a real traffic disruption from a technical artifact (lost connection or power).
- **FR3.** A map showing where anomalies happen. Selecting a point on the map or on a chart (especially a mega-anomaly) opens a side panel with the exact time, the size of the deviation and, if known, a description of the outside news event that caused it.
- **FR4.** A separate section that compares algorithms: which anomalies our logic found, which ones the corporate system found, where they agree and where they differ. The section must clearly show how well the new approach works.

## Non-functional requirements

- **NFR1.** Screen width from 1200px to 1920px.
- **NFR2.** The last 3 versions of Chrome and Yandex Browser.
- **NFR3.** Critical endpoints handle up to 100 requests per second.
- **NFR4.** Critical endpoints respond in 1000 ms or less.
- **NFR5.** Traffic is encrypted with HTTPS.
