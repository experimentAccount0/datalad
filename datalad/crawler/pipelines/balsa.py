# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##

"""A pipeline for crawling BALSA datasets"""

import os, re
from os import curdir, listdir
from os.path import lexists, join as opj

# Import necessary nodes
from ..nodes.crawl_url import crawl_url
from ..nodes.matches import xpath_match, a_href_match
from ..nodes.misc import assign, skip_if
from ..nodes.misc import find_files
from ..nodes.annex import Annexificator
from ...consts import ARCHIVES_SPECIAL_REMOTE
from datalad.support.annexrepo import *
from datalad.support.gitrepo import *

from logging import getLogger
lgr = getLogger("datalad.crawler.pipelines.balsa")

TOPURL = "http://balsa.wustl.edu/study"


def superdataset_pipeline(url=TOPURL):
    """
    Parameters
    ----------
    url: str
       URL point to all datasets, hence the URL at the top
    -------

    """
    annex = Annexificator()
    lgr.info("Creating a BALSA collection pipeline")
    return [
        crawl_url(url),
        xpath_match('//*/tr/td[1]/a/text()', output='dataset'),
        # skip the empty dataset used by BALSA for testing
        skip_if({'dataset': 'test study upload'}, re=True),
        assign({'dataset_name': '%(dataset)s'}, interpolate=True),
        annex.initiate_dataset(
            template="balsa",
            data_fields=['dataset'],
            existing='skip'
        )
    ]


# def extract_readme(data):
#
#     data['title'] = xpath_match('//*/p[1]|span/text()')(data)
#     data['species'] = xpath_match('//*/p[2]|span/text()')(data)
#     data['description'] = xpath_match('//*/p[3]|span/text()')(data)
#     data['publication'] = xpath_match('//*/p[4]|span/text()')(data)
#     data['full tarball'] = xpath_match('//*[@class="btn-group"]/a[contains(text(), "d")]')(data)
#
#     if lexists("README.txt"):
#         os.unlink("README.txt")
#
#     with open("README.txt", "w") as fi:
#         fi.write("""\
# BALSA sub-dataset %(dataset)s
# ------------------------
#
# Full Title: %(title)s
# Species: %(species)s
#         """ % data)
#
#         lgr.info("Generated README.txt")
#         yield {'filename': "README.txt"}


@auto_repr
class BalsaSupport(object):

    def __init__(self, repo, path):
        """Verifies that the canoncial tarball contains all files that are
        individually listed

           Parameters
           ----------
           repo: str
             annex repo to which dataset is being annexed
           path: str
             path to directory where dataset is being stored
           """
        self.repo = repo
        self.path = path

    def verify_files(self):

        files_path = opj(path, '_files')

        con_files = listdir(path)  # list of files that exist from canonical tarball
        files = listdir(files_path)  # list of file that are individually downloaded
        files_key = [self.repo.get_file_key(item) for item in files]

        for item in con_files:
            if item in files:
                key = self.repo.get_file_key(item)
                if key in files_key:
                    pass
                else:
                    lgr.warning("%s is varies in content from the individually downloaded "
                                "files, is removed and file from canonical tarball is kept" % item)
                p = opj(files_path, item)
                self.repo.remove(p)
            else:
                lgr.warning("%s does not exist in the individaully listed files by name, "
                            "but will be kept from canconical tarball" % item)
        if files:
            lgr.warning("The following files do not exist in the canonical tarball, but are "
                        "individaully listed files and will not be kept" % files)


def pipeline(dataset):
    lgr.info("Creating a pipeline for the BALSA dataset %s" % dataset)
    annex = Annexificator(create=False, statusdb='json', special_remotes=[ARCHIVES_SPECIAL_REMOTE],
                          options=["-c",
                                   "annex.largefiles="
                                   "exclude=Makefile and exclude=LICENSE* and exclude=ISSUES*"
                                   " and exclude=CHANGES* and exclude=README*"
                                   " and exclude=*.[mc] and exclude=dataset*.json"
                                   " and exclude=*.txt"
                                   " and exclude=*.json"
                                   " and exclude=*.tsv"
                                   ])
    balsa = BalsaSupport(repo=annex.repo, path=curdir)
    # BALSA has no versioning atm, so no changelog either

    return [
        annex.switch_branch('incoming'),
        [
            crawl_url(TOPURL),
            [
                assign({'dataset': dataset}),
                skip_if({'dataset': 'test study upload'}, re=True),
                # canonical tarball
                a_href_match('http://balsa.wustl.edu/study/download/', min_count=1),
                annex,
            ],
            [
                assign({'path': '_files/%(path)s'}, interpolate=True),
                annex,
            ],

        ],
        annex.remove_obsolete(),
        [
            annex.switch_branch('incoming-processed'),
            annex.merge_branch('incoming', one_commit_at_a_time=True, strategy='theirs', commit=False),
            [
               {'loop': True},
               find_files("\.(zip|tgz|tar(\..+)?)$", fail_if_none=True),
               annex.add_archive_content(
                   existing='archive-suffix',
                   strip_leading_dirs=True,
                   leading_dirs_depth=1,
                   delete=True,
                   exclude=['(^|%s)\._' % os.path.sep],
               ),
            ],
            verify_files(balsa),
            annex.switch_branch('master'),
            annex.merge_branch('incoming-processed', commit=True),
            annex.finalize(tag=True),
        ],
        annex.switch_branch('master'),
        annex.finalize(cleanup=True),
    ]
