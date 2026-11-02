Runner AI
#####


This repository implements the setup to use AI to help you train for the Marathon, just as I do. I want to approach that task with the new tech and use the smartiness of LLMs to deliver the best results. 

DISCLAIMER. No advices here, you use that on your own risk. Consult with professional trainers or medical specialists where necessary.

How it works:
- there is the `data` folder that is excluded from this repo
  - the repository point to the same-named repo with `-data` suffix
  - the repository is created if missing and keeps all the personal data
- main repository contains sharable scripts
  - to fetch runs to the `data` folder from Strava and Nike+
  - to maintain layout of type `run-<year>-<month>-<date>[optional salt]`
  - each run folder contains all the information about the rum
- we use skills and README to explain the core agent how to deal with the data
- agent must ask additional questions to augment the data
- only user inputs are presisted and pushed to the Git repository
- we keep all intermediate agentic output in the `slop` folder, which is ignored. The main reason of that is to make sure Agents can reason on the data, and not use it's previous reasoning results as input. The only exceptions is when peer review is implemented.
- the project is written in Python (or what is the easiest so far)
- the project implements OAuth2 login with Strava and only asks minimal permissions
- the `data` folder contains the GOALS.md the file explaining the current goals and marathons planned for the athlete


Contributions
###

We are open for contributions, please share what you think. Be careful submitting personal data into the repo. 
