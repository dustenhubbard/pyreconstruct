kh_web = "https://synapseweb.clm.utexas.edu/harrislab"
kh_wiki = "https://wikis.utexas.edu/display/khlab/PyReconstruct+user+guide"
kh_atlas = "https://synapseweb.clm.utexas.edu/atlas"
# This fork, where all in-app menu links (source code, issues, feature requests)
# point. Upstream provenance is credited in the README and the About dialog.
fork_repo = "https://github.com/dustenhubbard/PyReconstruct"
# Source-code menu link (Help > Online resources > "PyReconstruct source code").
gh_repo = fork_repo
# User-guide menu link (Help > Online resources > "PyReconstruct user guide").
gh_wiki = fork_repo + "/wiki"
gh_issues = fork_repo + "/issues"
# The two issue forms (.github/ISSUE_TEMPLATE/*.yml), opened by their own Help
# rows. Each URL names its form directly rather than going through GitHub's
# chooser page, because only a direct form link can carry prefilled fields:
# error_report.prefilled_issue_url appends the version/OS/Python lines.
gh_bug_form = gh_issues + "/new?template=bug.yml"
gh_feature_form = gh_issues + "/new?template=feature.yml"
