# manual — behavioral, played by the auditor

Config: track=behavioral, role=Machine Learning Engineer, level=mid, framework=amazon, custom_questions='Tell me about a time you shipped something you were not proud of.' Clock advanced 30 s per exchange. The silent turn after the fifth candidate answer is F1 in ../../AGENT_AUDIT_2026-09.md; the worker log at that moment: 'maximum number of function calls steps reached'.

**FLOW** `self_intro`: Great to have you here, Pranav Mishra! Are you ready to begin?

_event_: {"type": "stage_change", "stage": "self_intro"}


**ME** `self_intro`: Yeah, ready. Quick question first though - how long is this going to take? I have a call in 25 minutes.

**FLOW** `self_intro` _(0.7s)_: I appreciate you letting me know, Pranav. The interview should take around 20-25 minutes, so we should be able to cover everything in that time. Let's get started! 

Could you briefly introduce yourself and share your background with me?


**ME** `self_intro`: Cool. So I'm Pranav, I've been doing ML engineering for about four years. Right now I work on a recommendations team at a mid-size e-commerce company, mostly the ranking models and the feature pipeline that feeds them. Before that I did a couple of years of data engineering. I like the messy end of ML - getting things into production and keeping them there - more than the modeling itself honestly.

**FLOW** `self_intro` _(7.0s)_: Thank you for sharing that, Pranav! Can you tell me more about your current role and the specific projects you're working on?


**ME** `self_intro`: Sure. The main thing this year was moving our ranking model retraining from a weekly manual job to a daily automated pipeline. I owned the feature store side and the validation gates. Also a smaller thing - I built a shadow-deployment setup so we can run a candidate model against live traffic without serving it.

**FLOW** `behavioral_q1` _(5.0s)_: Thank you for that insight, Pranav! Now that I have a clearer understanding of your background and current role, let's dive into some behavioral questions. 

Could you describe a challenging problem you faced in your role and how you approached solving it?

_event_: {"type": "stage_change", "stage": "behavioral_q1"}


**ME** `behavioral_q1`: Okay so, um, a time I had to deliver under pressure... Last November, right before peak season, our ranking model started degrading - click-through dropped about 8 percent over three days. Nobody knew why. I was the one on call. I pulled the feature distributions and found one upstream team had changed how they logged product categories, so a third of our category features were basically null. I wrote a fallback mapping, got it reviewed and deployed in about six hours, and CTR recovered the next day. Afterwards I added distribution drift checks so it would page us instead of us finding out from the dashboard.

**FLOW** `behavioral_q1` _(2.9s)_: Great, Pranav Mishra! Let's move into the behavioral questions. Can you tell me about a time you shipped something you were not proud of?


**ME** `behavioral_q1`: Hm. Honestly, the first version of that shadow deployment thing. I shipped it with the comparison metrics computed in a notebook that I ran by hand, because the deadline was a demo to the VP. It worked for the demo. Then for two months people were making model decisions off numbers that only I could regenerate, and once I was on vacation and nobody could. I should have pushed the demo back a week and built the metrics job properly.


**ME** `behavioral_q1`: Wait, before the next one - can I ask, was that a reasonable answer? Like is that the kind of thing you're looking for, or too negative?

**FLOW** `behavioral_q1` _(1.6s)_: That was a reasonable answer, Pranav. It's important to reflect on experiences where things didn't go as planned, as it shows your ability to learn from mistakes and take ownership. Sharing how you would have approached the situation differently demonstrates growth and awareness, which are valuable traits in a Machine Learning Engineer. 

Now, let's continue with a follow-up. What exactly was your responsibility in that scenario?


**ME** `behavioral_q1`: I mean, I said - it was my project, I built it and I made the call to ship with the notebook. My manager knew about the tradeoff but I'm the one who proposed it.

**FLOW** `behavioral_q2` _(3.5s)_: Thank you for your detailed responses, Pranav! We've gathered some valuable insights from that behavioral question. Now, let's move on to another question. 

Can you tell me about a time when you had to make a difficult technical decision? What was the situation, and how did you approach it?

_event_: {"type": "stage_change", "stage": "behavioral_q2"}


**ME** `behavioral_q2`: Sorry, can you repeat the question? I missed the second half.

**FLOW** `behavioral_q2` _(1.3s)_: Of course, Pranav! The question is: Can you tell me about a time when you had to make a difficult technical decision? What was the situation, and how did you approach it?


**ME** `behavioral_q2`: Right. Um, I disagreed with our tech lead about whether to retrain daily or weekly. He thought daily was overkill and would burn compute budget. I ran the numbers on staleness - showed CTR decayed about 1.5 percent by day five after each weekly retrain - and proposed daily with a cheaper incremental job. We compromised on every two days and it's been fine. I think being able to show the decay curve is what moved it, not the argument.

**FLOW** `behavioral_q2` _(4.8s)_: Good. Let's move on to the next question. Can you share the specific actions you took to gather the data on CTR decay?


_closed_

