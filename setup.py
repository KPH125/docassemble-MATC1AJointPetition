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

setup(name='docassemble.MATC1AJointPetition',
      version='2.0.1',
      description=('A docassemble interview to prepare and file papers to initiate a joint 1A divorce petition in Massachusetts.'),
      long_description='This interview is the home base from which to initiate a 1A divorce. \r\n\r\nInterview generates:\r\n- Joint petition (CJ-D 101A)\r\n- Record of absolute divorce (R408)\r\n- Affidavit of irretrievable breakdown\r\n\r\nInterviews needed if children:\r\n- Child care or custody disclosure (w/supplement for 5-9 children)\r\n- Child support guidelines worksheet (CJD-304)\r\n- Findings and Determnations for Child Support and Post-Secondary Education (CJD 305) *cout wants always starting 2026\r\n\r\nAdditional filings:\r\nThese forms are not required at initial filing but may need to be filed before hearing can be assigned date or occur\r\n- Financial statement (per u in users, u=2)\r\n- Separation Agreement \r\n- Affidavit of indigency (per u_indigent in users )\r\n- Motion for temporary orders & supporting affidavit (if needed)\r\n- Proposed Order\r\n',
      long_description_content_type='text/markdown',
      author='KP Hunsinger',
      author_email='litlab@suffolk.edu',
      license='MIT',
      url='https://docassemble.org',
      packages=find_namespace_packages(),
      install_requires=[],
      zip_safe=False,
      package_data=find_package_data(where='docassemble/MATC1AJointPetition/', package='docassemble.MATC1AJointPetition'),
     )
