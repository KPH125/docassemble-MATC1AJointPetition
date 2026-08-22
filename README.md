# Massachusetts joint 1A divorce

This Docassemble package prepares forms for a Massachusetts joint 1A divorce.

## Project documentation

- [Clinic workspace documentation](docs/clinic_workspace/README.md) describes the
  student-clinician caseload dashboard, persistent matter workspace,
  supervision model, document lifecycle, access controls, and testing strategy.
- [Combined interview certification](tests/certification/README.md) describes the
  exhaustive path and screen-coverage system for the existing combined interview.

The clinic workspace has passed its isolated, authenticated Docassemble runtime
certification. It has not been deployed for client work. Production use still
requires operator approval of the target server's authentication, storage,
backup, retention, and monitoring controls.

[Data mapping dictionary updated 6/10/26](https://github.com/user-attachments/files/28799430/17_1A_Divorce_Field_Map_Team_Handoff_2026-06-09.xlsx)
and [updated 7/7/26 information about spouse attributes](https://github.com/SuffolkLITLab/docassemble-MATC1ADivorceJointPetition/wiki/Data-Dictionary-%E2%80%90-Spouses)

[Project Overview](https://github.com/user-attachments/files/28799522/Divorce1AProjectOverview.docx)

## Supported documents

The package can prepare the following initial documents.

- Joint Petition for Divorce (CJ-D 101A)
- Report of Absolute Divorce or Annulment (R408)
- Affidavit of Irretrievable Breakdown
- Motion to convert an existing 1B case to a joint 1A case

Matters involving children may also require these documents.

- Affidavit Disclosing Care or Custody Proceedings
- Child Support Guidelines Worksheet (CJ-D 304)
- Findings and Determinations for Child Support and Post-Secondary Education
  (CJ-D 305)

The package also supports a late marriage-certificate motion, financial
statements for either party, a separation agreement, an affidavit of indigency,
and a temporary-orders packet containing a motion, supporting affidavit, and
proposed order.
