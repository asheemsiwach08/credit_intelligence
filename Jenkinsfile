pipeline {
    agent {
        label "${env.BRANCH_NAME == 'dev_main' ? 'dev-agent' : 'main'}"
    }

    triggers {
        githubPush()
    }

    environment {
        BRANCH_NAME = "${env.BRANCH_NAME}"
        AWS_REGION = 'ap-south-1'
        DOCKER_REGISTRY = '676206929524.dkr.ecr.ap-south-1.amazonaws.com'
        DOCKER_IMAGE = 'dev-orbit-pem'
        DOCKER_NAME = "ASEEM"
        DOCKER_TAG = "${DOCKER_IMAGE}:${DOCKER_NAME}${BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Inject .env from Jenkins Secret File') {
            steps {
                withCredentials([file(credentialsId: 'aseem_env', variable: 'ENV_FILE1')]) {
                    sh 'rm -f .env'
                    sh 'cp $ENV_FILE1 .env'
                }
            }
        }

        stage('Setup Python Env & Install Dependencies') {
            steps {
                sh '''
                    python3 -m venv venv
                    source venv/bin/activate
                    pip install --upgrade pip
                    pip install -r requirements.txt
                    deactivate
                '''
            }
        }

        stage('Login to AWS ECR') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'aws-credentials', usernameVariable: 'AWS_ACCESS_KEY_ID', passwordVariable: 'AWS_SECRET_ACCESS_KEY')]) {
                    sh '''
                        bash -c '
                        export AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID"
                        export AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY"
                        aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin 676206929524.dkr.ecr.ap-south-1.amazonaws.com
                        '
                    '''
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                sh 'docker build -t ${DOCKER_TAG} .'
            }
        }

        stage('Tag Docker Image') {
            steps {
                sh 'docker tag ${DOCKER_TAG} ${DOCKER_REGISTRY}/${DOCKER_TAG}'
            }
        }

        stage('Push Docker Image to ECR') {
            steps {
                sh 'docker push ${DOCKER_REGISTRY}/${DOCKER_TAG}'
            }
        }

        stage('Stop and Remove Old Docker Container Running on Port 9000') {
            steps {
                sh '''
                    container_id=$(docker ps -q --filter "publish=9000")
                    if [ -n "$container_id" ]; then
                        docker stop $container_id
                        docker rm $container_id
                        echo 'Old container stopped and removed'
                    else
                        echo 'No container running on port 9000'
                    fi
                '''
            }
        }

        stage('Run New Docker Container on Port 9000') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'aws-credentials', usernameVariable: 'AWS_ACCESS_KEY_ID', passwordVariable: 'AWS_SECRET_ACCESS_KEY')]) {
                    sh '''
                        bash -c '
                        export AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID"
                        export AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY"
                        docker run -d -p 9000:9000 \
                            -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
                            -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
                            ${DOCKER_REGISTRY}/${DOCKER_TAG}
                        '
                    '''
                }
            }
        }
    }

    post {
        success {
            slackSend (
                tokenCredentialId: 'slack_channel_secret',
                message: "✅ Build SUCCESSFUL: ASHEEM${env.JOB_NAME} [${env.BUILD_NUMBER}]",
                channel: '#jenekin_update',
                color: 'good',
                iconEmoji: ':white_check_mark:',
                username: 'Jenkins'
            )
        }
        failure {
            slackSend (
                tokenCredentialId: 'slack_channel_secret',
                message: "❌ Build FAILED: ${env.JOB_NAME} [${env.BUILD_NUMBER}]",
                channel: '#jenekin_update',
                color: 'danger',
                iconEmoji: ':x:',
                username: 'Jenkins'
            )
        }
        always {
            cleanWs()
        }
    }
}
