pipeline{
    agent any

    triggers {
        githubPush()  // Trigger build on GitHub push
    }

    stages{
        stage('Checkout') {
                // when {
                //     expression { return  env.GIT_BRANCH == 'refs/heads/main' }
                // }
                steps {
                    checkout scm
                }
            }
    }
}