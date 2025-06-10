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
                withCredentials([file(credentialsId: 'aseem_env', variable: 'ENV_FILE1')]) {
                    chmod +x .
                    sh 'cp $ENV_FILE1 .env'
                }
            }
        }
        stage('Setup Python Env & Install Dependencies') {
            // when {
            //     branch 'main'
            // }
            steps {
                sh '''
                python3 -m venv venv
                source venv/bin/activate
                pip install --upgrade pip
                pip install -r requirements.txt
                '''
            }
        }
    }
}