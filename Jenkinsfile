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
        stage('Inject .env from Jenkins Secret File') {
            // when {
            //     branch 'main'
            // }
            steps {
                withCredentials([file(credentialsId: 'aseem_env', variable: 'ENV_FILE')]) {
                    sh 'cp $ENV_FILE .env'
                }
            }
        }
    }
}