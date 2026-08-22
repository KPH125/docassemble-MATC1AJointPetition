import os
import sys
from setuptools import setup, find_namespace_packages
from fnmatch import fnmatchcase
from distutils.util import convert_path

standard_exclude = ('*.pyc', '*~', '.*', '*.bak', '*.swp*')
standard_exclude_directories = ('.*', 'CVS', '_darcs', './build', './dist', 'EGG-INFO', '*.egg-info')

def find_package_data(where='.', package='', exclude=standard_exclude, exclude_directories=standard_exclude_directories):
    out = {}
    stack = [(convert_path(where), '', package)]
    while stack:
        where, prefix, package = stack.pop(0)
        for name in os.listdir(where):
            fn = os.path.join(where, name)
            if os.path.isdir(fn):
                bad_name = False
                for pattern in exclude_directories:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        break
                if bad_name:
                    continue
                if os.path.isfile(os.path.join(fn, '__init__.py')):
                    if not package:
                        new_package = name
                    else:
                        new_package = package + '.' + name
                        stack.append((fn, '', new_package))
                else:
                    stack.append((fn, prefix + name + '/', package))
            else:
                bad_name = False
                for pattern in exclude:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        break
                if bad_name:
                    continue
                out.setdefault(package, []).append(prefix+name)
    return out

setup(name='docassemble.MATC1ADivorceJointPetition',
      version='2.0.1',
      description=('A docassemble interview to prepare and file papers to initiate a joint 1A divorce petition in Massachusetts.'),
      long_description='This interview is the home base from which to initiate a 1A divorce. \r\n\r\n[Data mapping dictionary updated 6/10/26](https://github.com/user-attachments/files/28799430/17_1A_Divorce_Field_Map_Team_Handoff_2026-06-09.xlsx)\r\nand [updated 7/7/26 information about spouse attributes](https://github.com/SuffolkLITLab/docassemble-MATC1ADivorceJointPetition/wiki/Data-Dictionary-%E2%80%90-Spouses)\r\n\r\n[Project Overview](https://github.com/user-attachments/files/28799522/Divorce1AProjectOverview.docx)\r\n\r\n\r\nInterview generates:\r\n\r\n  - Joint petition (CJ-D 101A) \r\n  - Record of absolute divorce (R408) and\r\n  - Affidavit of irretrievable breakdown\r\n  \r\nOr\r\n\r\n  - Motion to convert from 1B to 1A\r\n\r\nInterviews needed if children:\r\n- Child care or custody disclosure (w/supplement for 5-9 children)\r\n- Child support guidelines worksheet (CJD-304)\r\n- Findings and Determnations for Child Support and Post-Secondary Education (CJD 305) *court wants for all cases with children starting 2026\r\n\r\nAdditional filings:\r\n- Certified copy of marriage certificate (upload) (or motion to file late )\r\n\r\nThese forms are not required at initial filing but may need to be filed before hearing can be assigned date or occur\r\n- Financial statement (per u in users, u=2)\r\n- Separation Agreement \r\n- Affidavit of indigency (per u_indigent in users )\r\n- Motion for temporary orders (if needed) \r\n    - supporting affidavit \r\n    - Proposed Order\r\n',
      long_description_content_type='text/markdown',
      author='KP Hunsinger',
      author_email='litlab@suffolk.edu',
      license='MIT',
      url='https://docassemble.org',
      packages=find_namespace_packages(),
      install_requires=[
          'docassemble.ALAffidavitOfIndigency>=2.3.0',
          'docassemble.MATCMotionToAmend @ git+https://github.com/SuffolkLITLab/docassemble-MATCMotionToAmend.git@f92797e3c417f142faec40fbce35d25fb8bf50d6',
          'docassemble.MATCFinancialStatement @ git+https://github.com/SuffolkLITLab/docassemble-MATCFinancialStatement.git@a1dbe3d228c7f36674217103abb082ae35610741',
          'docassemble.MATCSeparationAgreement @ git+https://github.com/SuffolkLITLab/docassemble-MATCSeparationAgreement.git@dce8a19a3249a7be750ddc326913bc2bb93c6dfe',
          'docassemble.MATCChildCareOrCustodyDisclosureAffidavit @ git+https://github.com/SuffolkLITLab/docassemble-MATCChildCareOrCustodyDisclosureAffidavit.git@08f31c860457e41ea757d3b1f8469c74a7a53556',
          'docassemble.MATCCSGWorksheet @ git+https://github.com/SuffolkLITLab/docassemble-MATCCSGWorksheet.git@96589474face58e0bbb18a067f4710e8e50e3d5a',
          'docassemble.matcfindingsanddeterminations @ git+https://github.com/SuffolkLITLab/docassemble-MATCFindingsAndDeterminations.git@9ce10b5f65b0fdd83919d151dee6d9a717723b26',
      ],
      zip_safe=False,
      package_data=find_package_data(where='docassemble/MATC1ADivorceJointPetition/', package='docassemble.MATC1ADivorceJointPetition'),
     )
