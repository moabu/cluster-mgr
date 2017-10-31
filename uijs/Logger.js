import React, {Component} from "react";
import ReactDOM from "react-dom";
import axios from 'axios';

import LogItem from './logitem';
import MessageItem from './messageitem'

class LogContainer extends Component {

    constructor(props) {
        super(props);
        this.state = {
            items: this.props.items
        }
    }

    scrollToBottom() {
        const node = ReactDOM.findDOMNode(this.logEnd);
        node.scrollIntoView({ behavior: "smooth" });
    }

    componentDidMount() {
        this.scrollToBottom();
    }

    componentDidUpdate() {
        this.scrollToBottom();
    }

    render() {
        const msgItems = this.props.items.map(itemInfo => {
            if (itemInfo.hasOwnProperty('output') && itemInfo.hasOwnProperty('action')){
                const {id, action, state, output} = itemInfo;
                return (
                    <LogItem
                        key={id}
                        id={id}
                        action={action}
                        state={state}
                        output={output}
                        server={this.props.server}
                    />
                );
            } else {
                // TODO pass the the individual properties instead of itemInfo object
                return (
                    <MessageItem
                        key={Math.random()}
                        level={itemInfo.level}
                        msg={itemInfo.msg}
                    />
                );
            }
        });

        return (
            <div className={this.props.show ? "log-body" : "hidden"}>
                {msgItems}
                <div style={{ float:"left", clear: "both" }} ref={(el) => { this.logEnd = el; }}></div>
            </div>
        )
    }
}

class Logger extends Component {
    constructor(props) {
        super(props);
        this.state = {
            logData: {
                messages: []
            },
            showContent: true
        };
        this.fetchData = this.fetchData.bind(this);
        this.toggleContentView = this.toggleContentView.bind(this);
    }

    componentDidMount() {
        this.timerID = setInterval(
            () => this.fetchData(),
            500
        );
    }

    fetchData() {
        const id = document.clustermgr.task_id;
        axios.get("/log/" + id).then(
            (response) => {
                this.setState({logData: response.data});
                if (response.data.state === 'SUCCESS' || response.data.state === 'FAILURE') {
                    clearInterval(this.timerID);
                }
            }
        );
    }

    componentWillUnmount() {
        clearInterval(this.timerID);
    }

    toggleContentView(){
        this.setState(prevState => ({showContent: !prevState.showContent}))
    }

    render() {
        return (
            <div className="logger">
                <div className="row log-header">
                    <div className="col-md-8">
                    </div>
                    <div className="col-md-4">
                        { this.state.showContent
                            ?
                            <button className={"logger-button pull-right"} onClick={this.toggleContentView}>
                            <i className="glyphicon glyphicon-eye-close"/>  Hide Logs</button>
                            :
                            <button className={"logger-button pull-right"} onClick={this.toggleContentView}>
                                <i className="glyphicon glyphicon-eye-open"/>  Show Logs</button>
                        }
                    </div>
                </div>
                <LogContainer items={this.state.logData.messages} show={this.state.showContent} server={"example.com"}/>
            </div>
        )
    }
}

ReactDOM.render(
    <Logger/>,
    document.getElementById('log_root')
);
