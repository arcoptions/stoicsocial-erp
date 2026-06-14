# TITLE PAGE

AMITY UNIVERSITY ONLINE, NOIDA, UTTAR PRADESH

In partial fulfilment of the requirement for the award of degree of Bachelor of Computer Applications (Discipline - IT)

Project Title:
StoicSocial ERP for Inventory and Print Operations

Guide Details:
Name: P Sri Ram Charan Tej
Designation: Project Guide

Submitted By:
Name of the Student: Abhiram Narla
Enrolment No: ____________________
Academic Year: 2025-2026

---

# ABSTRACT

StoicSocial ERP is an internal operations project developed for a print-on-demand apparel workflow. In many growing businesses, teams handle orders, print scheduling, receiving, and stock correction in separate tools. This creates delays, duplicate effort, and status confusion. The core objective of this project is to solve that coordination gap by designing one reliable system for daily internal operations.

The project is implemented using Django and PostgreSQL with clearly defined data entities for orders, order lines, printed SKUs, blank SKUs, print jobs, print job lines, and stock movements. The system design focuses on practical process control. Instead of informal manual updates, each stage follows explicit workflow states. This helps operations teams understand what to do next and reduces uncertainty during handoff between teams.

The workflow begins with order readiness and print requirement detection. Once printable demand is identified, users can create print batches, generate print-related documents, and maintain visibility of current and previous print jobs. Historical visibility is important because teams often need to compare ongoing work with recently completed batches. By keeping this history available in the operations flow, the project supports faster decisions and fewer repetitive checks.

Receive operations are also a key part of this study. In print-on-demand execution, receiving completed production and updating inventory correctly is one of the most sensitive points. Any mismatch at this stage affects shipment readiness and customer timelines. StoicSocial ERP addresses this through structured receive screens and stock movement logging so that quantity changes are recorded and traceable.

Data integrity is treated as a primary requirement in the implementation. Stock-related operations are designed with transaction-safe patterns to reduce inconsistency risks. Domain logic is maintained in dedicated service workflows, while UI templates and route handlers focus on user interaction. This separation improves maintainability and makes testing more systematic.

The project also includes practical quality assurance support. Scenario seeding, route-level checks, and repeatable validation scripts are used to evaluate behavior across common order and print states. This approach helps confirm that the system works consistently not only in ideal conditions but also in operational edge situations.

Another important aspect is usability alignment between user-facing operations pages and administrative controls. Internal teams should not lose workflow context while completing tasks. Therefore, this project emphasizes navigable routes, clear page hierarchy, and continuity between planning, generation, receiving, and review steps. This usability layer supports faster adoption and reduces avoidable operational errors.

From a business perspective, the project demonstrates measurable operational value. Teams get better visibility on pending and urgent work, can access previous print batches quickly, and can reconcile stock changes with higher confidence. The ERP approach also improves audit readiness because key actions are recorded in a structured manner.

In conclusion, StoicSocial ERP shows how a focused internal platform can improve coordination, consistency, and accountability in a print operations environment. The project contributes both a functional implementation and a process-oriented analysis model for internal operations management. Future enhancements can include deeper KPI analytics, configurable SLA alerts, advanced exception workflows, and role-based reporting exports for leadership review.

Keywords: ERP, inventory management, print operations, workflow automation, Django, internal operations platform

---

# CERTIFICATE

This is to certify that Abhiram Narla of Amity University Online has carried out the project work presented in this project report entitled "StoicSocial ERP for Inventory and Print Operations" for the award of Bachelor of Computer Applications under my guidance.

The project report embodies results of original work, and studies were carried out by the student. Certified further that, to the best of my knowledge, the work reported herein does not form the basis for the award of any other degree to the candidate or to anybody else from this or any other University/Institution.

Signature: ____________________
Name of Guide: P Sri Ram Charan Tej
Designation: ____________________
Date: ____________________
Place: ____________________

---

# DECLARATION

I, Abhiram Narla, a student pursuing Bachelor of Computer Applications at Amity University Online, hereby declare that the project work entitled "StoicSocial ERP for Inventory and Print Operations" has been prepared by me during the academic year 2025-2026 under the guidance of P Sri Ram Charan Tej.

I affirm that this project is an original bona-fide work done by me. It is the outcome of my own effort and it has not been submitted to any other university for the award of any degree.

Signature of Student: ____________________
Name: Abhiram Narla
Date: ____________________
Place: ____________________

---

# TABLE OF CONTENTS

1. Chapter 1: Introduction to the Topic
2. Chapter 2: Review of Literature
3. Chapter 3: Research Objectives and Methodology
4. Chapter 4: Data Analysis and Results
5. Chapter 5: Findings and Conclusion
6. Chapter 6: Recommendations and Limitations of the Study
7. Bibliography / References
8. Appendix

---

# LIST OF TABLES

1. Table 1: Order Lifecycle Status Categories
2. Table 2: Core Data Entities and Purpose
3. Table 3: QA Scenario Coverage Summary
4. Table 4: Module-Wise Validation Outcomes

---

# LIST OF FIGURES

1. Figure 1: High-Level System Flow
2. Figure 2: Print Batch to Receive Lifecycle
3. Figure 3: Inventory Mutation Control Flow
4. Figure 4: Operations Dashboard Navigation

---

# CHAPTER 1: INTRODUCTION TO THE TOPIC

## 1.1 Introduction

Digital-first businesses depend on smooth operations to deliver customer orders on time. In a print-on-demand model, delays often happen because printing, stock tracking, and order readiness are managed using separate tools. This project studies and implements an internal ERP approach to reduce these delays.

StoicSocial ERP focuses on practical operations. It gives one working platform for orders, print batches, receive updates, stock correction, and operational reporting. The project objective is not public customer interaction. The objective is strong internal control for daily execution teams.

## 1.2 Problem Context

Before standardization, teams usually face four recurring problems:

1. Status confusion between order handling and print handling.
2. Missing visibility of previous print jobs for quick reference.
3. Inconsistent stock updates during receive and adjustment activities.
4. Limited traceability for decision review and audit.

The project addresses these through structured workflows and clear screens for operations users.

## 1.3 Why This Topic Was Selected

This topic was selected because it combines business relevance with technical depth. It includes workflow design, data integrity, reporting usability, and automation testing. It also reflects real operational constraints where accuracy and speed must be balanced.

## 1.4 Company / Domain Context

The domain is print-on-demand apparel operations. The business receives orders, maps product variants, plans print batches, sends print packs to vendor teams, receives completed production, and prepares goods for shipping. StoicSocial ERP maps these activities into modules that can be measured and improved.

## 1.5 Scope of the Project

The system scope includes:

1. Internal order lifecycle management.
2. Print batch suggestion and confirmation.
3. Print pack and pick-list support.
4. Receive workflow and stock updates.
5. Inventory adjustments and stock movement logs.
6. Operational pages for audit, sales, and finance visibility.

The system excludes direct customer-facing UI and outbound e-commerce callbacks.

---

# CHAPTER 2: REVIEW OF LITERATURE

Enterprise systems research consistently shows that disconnected spreadsheets increase operational risk. Integrated ERP workflows improve traceability, process consistency, and managerial visibility. This principle is highly relevant in order-to-production environments.

Operations management studies also highlight that process handoff points are the most common source of delay. In print-on-demand models, handoffs occur between order processing, batch planning, vendor execution, and receiving. A centralized platform reduces ambiguity at these handoffs.

Inventory control literature emphasizes transaction safety and auditability. When stock updates are not synchronized, businesses face overcommitment, delayed shipping, and poor planning decisions. Systems that track stock movement events and maintain clear reason codes reduce these failures.

Software engineering literature recommends separating domain logic from UI layers to improve maintainability and testability. This project follows that design principle by keeping key operational behavior in service workflows and using templates/views for user interaction.

Recent studies on internal tooling indicate that simple user interfaces with clear action flows often produce better operational adoption than feature-heavy interfaces. Therefore, this project prioritizes practical navigation, fast visibility of recent jobs, and role-relevant pages.

The review supports the project direction: build an integrated, reliable, and testable internal operations platform with measurable workflow outcomes.

---

# CHAPTER 3: RESEARCH OBJECTIVES AND METHODOLOGY

## 3.1 Research Objectives

1. To design and validate a unified operations workflow for order, print, receive, and inventory stages.
2. To improve visibility of operational status and reduce manual ambiguity across teams.
3. To ensure stock mutation correctness through transaction-safe domain services.
4. To test whether standardized internal pages improve daily execution speed and confidence.

## 3.2 Research Problem

How can an internal ERP platform reduce workflow confusion and inventory inconsistency in a print-on-demand operations environment?

## 3.3 Research Design

The project uses an applied descriptive and evaluative design. It combines implementation with scenario-based validation.

## 3.4 Type of Data Used

1. Structured application data from orders, lines, print jobs, and stock logs.
2. Scenario data generated for QA coverage.
3. Route-level and module-level behavior observations.

## 3.5 Data Collection Method

Data was collected through controlled execution of operational workflows and validation of resulting state transitions.

## 3.6 Data Collection Instrument

1. Application route checks.
2. Seeded dataset execution scripts.
3. Functional verification through tests and smoke checks.

## 3.7 Sample Size

Sample size is defined as multi-scenario operational cases across major lifecycle states and module actions.

## 3.8 Sampling Technique

Purposive scenario sampling was used. Cases were selected to represent normal flow and exception flow.

## 3.9 Data Analysis Tool

Analysis was performed through status-transition verification, module-level output checks, and summary tracking of pass/fail outcomes.

---

# CHAPTER 4: DATA ANALYSIS AND RESULTS

## 4.1 Lifecycle Analysis

Order records were analyzed across common states such as new, needs printing, in printing, ready to ship, shipped, cancelled, and issue. The analysis confirmed that clearer transitions reduce confusion in handoff stages.

## 4.2 Print Workflow Results

The print batch process supports planning and confirmation with direct access to print documents. Historical print jobs improve repeatability and support quick reference during operational review.

## 4.3 Receive and Inventory Results

Receive operations and stock adjustments were validated for consistency. Stock movement records improve confidence in reconciliation and reduce guesswork during exception handling.

## 4.4 Routing and Navigation Results

Operations screens were reviewed for practical usability. Improved route consistency and direct access to key pages reduced extra navigation effort.

## 4.5 Testing Evidence Summary

1. Application checks and automated tests executed successfully for core flows.
2. Scenario seeding covered multiple lifecycle paths.
3. Smoke checks validated important pages and critical route availability.

The overall result indicates that the implemented ERP flow is suitable for internal operational control.

---

# CHAPTER 5: FINDINGS AND CONCLUSION

## 5.1 Findings

1. Integrated modules reduce dependency on disconnected trackers.
2. Visibility into previous print jobs supports faster operational decisions.
3. Transaction-safe stock update patterns improve data consistency.
4. Role-focused pages improve daily usability for operations teams.
5. Structured test workflows improve confidence before deployment.

## 5.2 Conclusion

The project demonstrates that StoicSocial ERP is an effective internal operations platform for a print-on-demand context. It improves status clarity, process consistency, and stock reliability while supporting practical team workflows. The implementation also shows that strong data integrity and simple UI design can coexist in internal tools. Based on observed outcomes, the project meets its primary objective of improving operational control.

---

# CHAPTER 6: RECOMMENDATIONS AND LIMITATIONS OF THE STUDY

## 6.1 Recommendations

1. Add SLA-based alerts for delayed operational stages.
2. Expand KPI dashboards for role-specific monitoring.
3. Add richer export formats for management review.
4. Introduce periodic data quality health checks.
5. Build deeper exception workflows for rare edge cases.
6. Add comparative analytics for batch performance trends.
7. Improve guided onboarding notes for new internal users.
8. Add more granular permission controls by role.
9. Add structured audit review reports by period.
10. Introduce environment-level release checklists.
11. Add proactive inventory risk indicators.
12. Extend test coverage for high-volume simulation.

## 6.2 Limitations of the Study

1. Study results are based on internal operational scenarios and may require adaptation for other domains.
2. Validation used controlled seed data rather than large live production variance.
3. Final performance benchmarking under very high load is outside current scope.
4. Integration coverage is intentionally limited to the defined internal workflow scope.
5. Some organizational process outcomes depend on team adoption behavior.
6. Visual reporting depth can be improved in future iterations.

---

# BIBLIOGRAPHY / REFERENCES

Kim, M. S., & Hunter, J. E. (1993). Attitude-behavior relations: A meta-analysis of attitudinal relevance and topic. Journal of Communication, 43(1), 101-142.

Laudon, K. C., & Laudon, J. P. (2020). Management information systems: Managing the digital firm. Pearson.

Monk, E., & Wagner, B. (2013). Concepts in enterprise resource planning. Cengage Learning.

Turban, E., Pollard, C., & Wood, G. (2018). Information technology for management. Wiley.

Django Software Foundation. (2026). Django documentation. https://docs.djangoproject.com/

PostgreSQL Global Development Group. (2026). PostgreSQL documentation. https://www.postgresql.org/docs/

---

# APPENDIX

## Appendix A: Suggested Screenshots to Attach

1. Orders page
2. Print batch page
3. Receive page
4. Forecast page
5. Inventory adjustment page
6. Audit log page
7. Admin print job listing

## Appendix B: Submission Notes

- Apply Times New Roman, size 12, double spacing in DOCX final copy.
- Insert running head and page numbers as required by university format.
- Replace blank signature/date/enrolment fields before final submission.
