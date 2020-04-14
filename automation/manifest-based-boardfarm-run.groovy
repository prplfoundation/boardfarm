def extra_args = env.extra_args ?: ''
def email_results = env.email_results ?: ''
def GERRIT_BRANCH = env.GERRIT_BRANCH ?: 'master'
def GERRIT_PROJECT = env.GERRIT_PROJECT ?: '.*'
def GERRIT_REFSPEC = env.GERRIT_REFSPEC ?: 'master'
def GERRIT_PORT = env.GERRIT_PORT ?: '29418'
def auto_user = (env.auto_user == null) ? "jenkins" : env.auto_user
env.auto_user = auto_user
// TODO: fetch from $auto_user in future
python_version = "3"

def meta = env.meta ?: ''
if (meta != '') {
    meta_args = " -m " + meta
} else {
    meta_args = ""
}

// board parameter is default board going forward
default_board = env.board
env.board = null

def sync_code () {
    println("Syncing code from gerrit")
    sshagent ( [ ssh_auth ] ) {
        script {
            sh "rm -rf *"
            sh "repo init -u " + manifest + " -m \${GERRIT_BRANCH:-default}.xml && repo sync --force-sync --force-remove-dirty -m \${GERRIT_BRANCH:-default}.xml"
            sh "repo forall -c 'git checkout gerrit/$GERRIT_BRANCH'"
            if (GERRIT_REFSPEC != '') {
                sh "repo forall -r ^$GERRIT_PROJECT\$ -c 'pwd && git fetch gerrit $GERRIT_REFSPEC && git checkout FETCH_HEAD && git rebase gerrit/$GERRIT_BRANCH'"
            }
            sh "repo manifest -r"
            sh "boardfarm/scripts/parse_commit_msg.sh"
        }
    }
}

def setup_python (version) {
    println("Setting up python version $version")
    if (version == "2") {
        sh '''

        if grep "$BUILD_URL" pip-check-build-py2; then
            . venv/bin/activate
        else
            rm -rf venv
            virtualenv venv
            . venv/bin/activate
            repo forall -c '[ -e "requirements.txt" ] && { pip install -r requirements.txt || echo failed; } || true '
            repo forall -c '[ -e "setup.py" ] && { pip install -e . || echo failed; } || true '
            echo $BUILD_URL > pip-check-build-py2
        }
        '''
    } else {
        sh '''
        if grep "$BUILD_URL" pip-check-build-py3; then
            . venv/bin/activate
        else
            rm -rf venv
            python3 -c 'import tkinter' || sudo apt install python3-tk
            python3 -m venv venv
            . venv/bin/activate
            pip3 install --upgrade pip
            repo forall -c '[ -e "requirements.txt" ] && { pip3 install -r requirements.txt || echo failed; } || true '
            repo forall -c '[ -e "setup.py" ] && { pip3 install -e . || echo failed; } || true '
            echo $BUILD_URL > pip-check-build-py3
        fi
        '''
    }
}

def post_gerrit_msg_from_file (file) {
    println("Posting message to gerrit from file")
    sh '''
    cat ''' +file

    sh '''
    ssh $auto_user@$GERRIT_HOST -p $GERRIT_PORT gerrit review $GERRIT_PATCHSET_REVISION \\'--message="$(cat ''' + file + ''')"\\'
    '''
}

def post_gerrit_msg (msg) {
    println("Posting message to gerrit")
    sh '''
    ssh $auto_user@$GERRIT_HOST -p $GERRIT_PORT gerrit review $GERRIT_PATCHSET_REVISION \\\'--message="''' + msg + '''"\\\'
    '''
}

def run_lint () {
    println("Running lint checks")
    setup_python(python_version)
    sh '''
    set +e
    pwd
    ls
    . venv/bin/activate
    # Run pre-commit, but undo changes it makes
    repo forall -c '[ -e ".pre-commit-config.yaml" ] && { pwd >>../pre-commit-results.txt; } && { pre-commit run --all-files >>../pre-commit-results.txt; } && { echo "\n" >> ../pre-commit-results.txt; } && { git reset --hard HEAD; }'
    # Run other checks
    rm -f errors.txt
    touch errors.txt
    repo forall -c 'git diff --name-only HEAD m/master | sed s,^,$REPO_PATH/,g' > files_changed.txt
    echo "Running pyflakes on py files and ignoring init files:"
    files_changed=`cat files_changed.txt | grep '\\.py$' | grep -v __init`
    if [ -z "$files_changed" ]; then
        touch errors.txt
        exit 0
    fi
    # Check for importing of pdb which can fill up disk and cause problems
    grep -H -n "import pdb" ${files_changed} | awk '{print $0" PDB IS NOT ALLOWED."}' >> errors.txt
    # Check for non-ascii characters
    grep --color='auto' -P -n "[^\\x00-\\x7F]" ${files_changed} | awk '{print $1" contains non-ascii characters."}' >> errors.txt
    # Check pyflakes errors
    python3 -m pyflakes ${files_changed} > flakes.txt 2>&1
    cat flakes.txt | grep -v 'devices\\.' | grep -v 'No such file' >> errors.txt
    # Check print errors
    grep -n -E '^\\s+print\\s' ${files_changed} | awk '{print $1" print should be function: print()"}' >> errors.txt
    # Check indentation errors
    flake8 --select=E111 ${files_changed} >> errors.txt
    # Check for bad line endings (we want linux line endings only)
    file ${files_changed} | grep 'with CRLF line' | awk -F: '{print $1": Run dos2unix on this file please."}' >> errors.txt
    '''

    precommit_fail_count = sh(returnStdout: true, script: """grep Failed pre-commit-results.txt | wc -l""") as Integer

    err_count = sh(returnStdout: true, script: """cat errors.txt | wc -l""") as Integer
    println("Found " + err_count + " errors in code")


    if (err_count > 3) {
        post_gerrit_msg("pyflakes found many errors")
    } else if (err_count > 0) {
        post_gerrit_msg_from_file("errors.txt")
    }

    archiveArtifacts artifacts: "*.txt"

    if (precommit_fail_count > 0) {
        post_gerrit_msg_from_file("pre-commit-results.txt")
        currentBuild.result = 'FAILED'
        error("pre-commit did not pass")
    }

    if (err_count > 0) {
        currentBuild.result = 'FAILED'
        error("pyflakes did not pass")
    }
}

def run_unittest () {
    println("Running unittests")
    setup_python(python_version)
    sh '''
        set +e
        . venv/bin/activate
        # Run unittests, store exit codes
        repo forall -c '[ -d "unittests" ] && { pytest unittests; echo $? >> ../unittest_results.txt; }'
        # If any exit code was 1, let's fail
        grep -q 1 unittest_results.txt
        if [ $? -ne 1 ]; then
            exit 1
        fi
        bft -l
    '''
}

def run_test (loc, ts, post, board) {
    env.loc = loc
    env.board = board
    println("Running in location = $loc, ts = $ts, and posting results = $post")
    ansiColor('xterm') {
        setup_python(python_version)

        if (ts == null) {
            sh '''
            pwd
            . ./.env
            . venv/bin/activate
            python --version
            bft --version
            export BFT_CONFIG="$(repo forall -c \"[ -e ''' + loc + '''.json ] && realpath ''' + loc + '''.json\")"
            ${WORKSPACE}/boardfarm/scripts/whatchanged.py --debug m/master HEAD
            export changes_args="`${WORKSPACE}/boardfarm/scripts/whatchanged.py m/master HEAD`"
            export PATH=$PATH:/home/$USER/bin
            if [ "$BFT_DEBUG" != "y" ]; then unset BFT_DEBUG; fi
            cd boardfarm
            for i in $(seq 1 1000); do
                ./bft -y -b ''' + board + ''' -x ''' + testsuite + ''' ${changes_args}''' + extra_args + meta_args + ''' && exit_code=$? || exit_code=$?
                echo bft exited with code = $exit_code

                if [ "$exit_code" = "0" ]; then
                    break
                else
                   sleep 30
                fi
            done
            '''
        } else {
            sh '''
            pwd
            . venv/bin/activate
            python --version
            bft --version
            export BFT_CONFIG="$(repo forall -c \"[ -e ''' + loc + '''.json ] && realpath ''' + loc + '''.json\")"
            if [ "$BFT_DEBUG" != "y" ]; then unset BFT_DEBUG; fi
            cd boardfarm
            for i in $(seq 1 1000); do
                ./bft -y -b ''' + board + ''' -x ''' + ts + ''' ''' + extra_args + meta_args + ''' && exit_code=$? || exit_code=$?

                echo bft exited with code = $exit_code

                if [ "$exit_code" = "0" ]; then
                    break
                else
                    sleep 30
                fi
            done
            '''

        }

        // TODO: only saves one of each board type (Board: mv1 mv1) - not a huge deal atm
        sh "mkdir -p  ${loc}/${board}/; mv boardfarm/results/* ${loc}/${board}/ || true"

        archiveArtifacts artifacts: "${loc}/${board}/*"

        if (post == true) {
            sh '''
            echo "Test results in ''' + loc + '''" > message
            echo "============" >> message
            cat ''' + loc + "/" + board + '''/test_results.json | jq '.test_results[] | [ .grade, .name, .message, .elapsed_time ] | @tsv' | \
            sed -e 's/"//g' -e "s/'//g" -e 's/\\\\t/\\t/g' -e 's/\\\\n/ /g' | \
               while read -r line; do
                   echo $line >> message
               done
            '''
            post_gerrit_msg_from_file("message")
        }

        sh "grep tests_fail...0, ${loc}/${board}/test_results.json"
    }
}

loc_arr = location.tokenize(' ')

def loc_cleanup = [:]
for (x in loc_arr) {
    def loc = x
    loc_cleanup[loc] = {
        node ('boardfarm && ' + loc) {
            sh 'rm -rf ' + loc
        }
    }
}

pipeline {
    agent { label 'boardfarm && ' + loc_arr[0] }


    options {
        skipDefaultCheckout(true)
    }

    stages {
        stage('checkout gerrit change') {

            steps {
                sync_code()
            }
        }

        stage('run linting') {
            steps {
                run_lint()
            }
        }

        stage('run unittests') {
            steps {
                run_unittest()
            }
        }

        stage('run selftest') {
            steps {
                script {
                    sh '''./boardfarm/scripts/parse_commit_msg.sh'''
                    boards = sh(returnStdout: true, script: '''. ./.env; echo $boards''')
                    if (!boards?.trim()) {
                        boards = default_board
                    }
                    testsuites  = sh(returnStdout: true, script: """. venv/bin/activate; python -c 'from boardfarm import find_plugins; print(" ".join([ getattr(v, "selftest_testsuite", "") for k, v in find_plugins().items() if hasattr(v, "selftest_testsuite") ]))'""")
                    def loc_selftest = [:]
                    idx = 1
                    for (board in boards.trim().tokenize(' ')) {
                        for (x in loc_arr) {
                            def loc = x
                            loc_selftest["${idx}: ${board}: $loc"] = {
                                stage("run selftest in $loc on board $board") {
                                    script {
                                        node ('boardfarm && ' + loc) {
                                            sync_code()
                                            setup_python(python_version)
                                            println("running testsuites = " + testsuites)
                                            for (ts in testsuites.trim().tokenize(' ')) {
                                                println("running testsuite  = " + ts)
                                                run_test(loc, ts, false, board)
                                            }
                                        }
                                    }
                                }
                            }
                            idx++
                        }
                    }
                    parallel loc_selftest
                }
            }
        }

        stage('run test') {
            steps {
                script {
                    sh '''./boardfarm/scripts/parse_commit_msg.sh'''
                    boards = sh(returnStdout: true, script: '''. ./.env; echo $boards''')
                    if (!boards?.trim()) {
                        boards = default_board
                    }
                    def loc_jobs = [:]
                    idx = 1
                    for (board in boards.trim().tokenize(' ')) {
                        for (x in loc_arr) {
                            def loc = x
                            loc_jobs["${idx}: ${board}: $loc"] = {
                                stage("run bft in $loc on board $board") {
                                    script {
                                        node ('boardfarm && ' + loc) {
                                            sync_code()
                                            run_test(loc, null, true, board)
                                        }
                                    }
                                }
                            }
                            idx++
                        }
                    }
                    parallel loc_jobs
                }
            }
        }

    }
    post {
        always {
            script {
                parallel loc_cleanup
            }

            println("cleaning up job")
            sh '''
            set +xe
            echo "Killing spawned processes..."
            PID_SELF=$$
            for PID in $(ps -eo pid,command -u ${USER} | grep -v grep | tail -n+2 | awk '{print $1}' | grep -v ${PID_SELF} | grep -v ${PPID}); do
                echo "Checking pid ${PID}"
                if xargs -0 -L1 -a /proc/${PID}/environ 2>/dev/null | grep "^BUILD_ID=${BUILD_ID}$"; then
                    if xargs -0 -L1 -a /proc/${PID}/environ 2>/dev/null | grep "^JOB_NAME=${JOB_NAME}$"; then
                        echo "Matched BUILD_ID=${BUILD_ID}$"
                        echo "Matched JOB_NAME=${JOB_NAME}$"
                        echo "Killing $(ps -p ${PID} | tail -1 | awk '{print $1}')"
                        sed -z 's/$/ /' /proc/$PID/cmdline; echo
                        kill ${PID}
                        echo killed ${PID}
                    fi
                fi
            done || true
            '''
        }
    }
}
